"""Traduce las excepciones previsibles a algo que la usuaria pueda resolver sola.

La app la usa una sola persona, que no es técnica, y corre en un servidor al que
no tiene acceso. Un traceback de Streamlit le dice que algo se rompió, pero no
qué hacer; eso es lo que arregla este módulo: cada fallo previsible se convierte
en **qué pasó**, **qué hacer** y, cuando corresponde, **a dónde ir**.

Sin Streamlit a propósito: acá solo se clasifica, y dibujar es trabajo de
``panel_error``. Así se puede probar con la excepción real sin levantar una app.

La regla que lo mantiene honesto: lo que no se reconoce devuelve ``None`` y
**se propaga**. Un ``except Exception`` que mostrara "ocurrió un error" para todo
esconderia los bugs de verdad, que es lo contrario de lo que hace falta.
"""

import re
from dataclasses import dataclass
from pathlib import Path

import httpx
from postgrest.exceptions import APIError

from planeacion.domain.errores import SinPedidosEnLaFecha, SinPedidosParaPivotear
from planeacion.infraestructura.adaptadores.salida.excel.lector_ecom import ColumnasEcomFaltantes

BD_SIN_CONEXION = "BD_SIN_CONEXION"
BD_CREDENCIALES = "BD_CREDENCIALES"
BD_MIGRACION_FALTANTE = "BD_MIGRACION_FALTANTE"
ARCHIVO_NO_RECONOCIDO = "ARCHIVO_NO_RECONOCIDO"
ARCHIVO_VACIO = "ARCHIVO_VACIO"
ARCHIVO_FECHA = "ARCHIVO_FECHA"

# Códigos de PostgREST/Postgres que significan "eso no existe en el esquema".
_TABLA_INEXISTENTE = ("42P01", "PGRST205")
_COLUMNA_INEXISTENTE = "42703"
# 401/403: la clave no sirve o no alcanza. PostgREST los devuelve con estos
# códigos propios, y a veces solo con el mensaje.
_NO_AUTORIZADO = ("PGRST301", "PGRST302", "401", "403", "42501")
_SENALES_DE_CLAVE = ("jwt", "invalid api key", "no api key", "unauthorized")

_PANEL_RENDER = "https://dashboard.render.com"
_REFERENCIA_SUPABASE = re.compile(r"https://([a-z0-9]+)\.supabase\.(co|in)", re.IGNORECASE)


def _carpeta_de_migraciones() -> Path | None:
    """Busca `migrations/` subiendo desde este archivo.

    Se busca en vez de fijar la cantidad de niveles porque contar carpetas se
    rompe en silencio la primera vez que alguien mueve un módulo: devolvería
    None y el aviso perdería el número de migración sin que nada falle.
    """
    for carpeta in Path(__file__).resolve().parents:
        candidata = carpeta / "migrations"
        if candidata.is_dir():
            return candidata
    return None


@dataclass(frozen=True)
class ErrorUsuario:
    """Un fallo previsible, ya traducido a instrucciones.

    ``codigo`` no es para la pantalla: va al log para poder filtrar en Render y
    para que quien reciba el aviso sepa de qué se está hablando.
    """

    codigo: str
    titulo: str
    que_paso: str
    que_hacer: tuple[str, ...]
    enlace: tuple[str, str] | None = None
    reintentable: bool = False


def panel_de_supabase(supabase_url: str | None) -> str | None:
    """``https://abc.supabase.co`` → el panel del proyecto, o None si no calza.

    Se deriva de la URL que ya está configurada en vez de pedir otra variable de
    entorno: una configuración más es una cosa más que puede quedar mal puesta.
    """
    if not supabase_url:
        return None
    encontrado = _REFERENCIA_SUPABASE.match(supabase_url.strip())
    if encontrado is None:
        return None
    return f"https://supabase.com/dashboard/project/{encontrado.group(1)}"


def migracion_de(nombre: str) -> str | None:
    """El número de la migración que crea esa tabla o columna, si se puede saber.

    Busca el nombre en los ``.sql`` de ``migrations/`` y devuelve el prefijo del
    primero que lo mencione. Si la carpeta no está donde se espera —un despliegue
    que solo copie ``src/``— devuelve None y el aviso va sin el número, que es
    mejor que no mostrar nada.
    """
    carpeta = _carpeta_de_migraciones()
    if not nombre or carpeta is None:
        return None
    patron = re.compile(rf"\b{re.escape(nombre)}\b", re.IGNORECASE)
    for archivo in sorted(carpeta.glob("*.sql")):
        if patron.search(archivo.read_text(encoding="utf-8")):
            return archivo.name.split("_", 1)[0]
    return None


def clasificar(excepcion: BaseException, supabase_url: str | None = None) -> ErrorUsuario | None:
    """La excepción → instrucciones, o None si no se reconoce (y se propaga).

    ``supabase_url`` llega por parámetro y no se lee del entorno acá adentro para
    que el módulo siga siendo puro: quien llama ya tiene los ajustes.
    """
    if isinstance(excepcion, APIError):
        return _clasificar_api(excepcion, supabase_url)
    if isinstance(excepcion, httpx.TransportError):
        return _sin_conexion(supabase_url)
    if isinstance(excepcion, ColumnasEcomFaltantes):
        return _archivo_no_reconocido(excepcion)
    # El orden importa: la de fecha es una subclase de la de archivo vacío.
    if isinstance(excepcion, SinPedidosEnLaFecha):
        return _archivo_de_otra_fecha(excepcion)
    if isinstance(excepcion, SinPedidosParaPivotear):
        return _archivo_vacio()
    return None


def _sin_conexion(supabase_url: str | None) -> ErrorUsuario:
    panel = panel_de_supabase(supabase_url)
    return ErrorUsuario(
        codigo=BD_SIN_CONEXION,
        titulo="La base de datos no responde",
        que_paso=(
            "No se pudo conectar con la base de datos. Suele pasar cuando el proyecto de "
            "Supabase se pausó solo por falta de uso."
        ),
        que_hacer=(
            "Entre al panel de Supabase con la cuenta de la empresa.",
            "Abra el proyecto de Planeación Logística.",
            'Si aparece pausado, presione "Restore" o "Resume".',
            "Espere 1 o 2 minutos y presione Reintentar acá abajo.",
            "Si su internet también está caído, revise la conexión antes de insistir.",
        ),
        enlace=("Abrir el panel de Supabase", panel) if panel else None,
        reintentable=True,
    )


def _clasificar_api(excepcion: APIError, supabase_url: str | None) -> ErrorUsuario | None:
    codigo = (excepcion.code or "").strip()
    mensaje = (excepcion.message or "").lower()

    if codigo in _NO_AUTORIZADO or any(senal in mensaje for senal in _SENALES_DE_CLAVE):
        return ErrorUsuario(
            codigo=BD_CREDENCIALES,
            titulo="La aplicación no tiene permiso para entrar a la base",
            que_paso=(
                "La base rechazó las credenciales. Las claves cambiaron o quedaron mal "
                "configuradas en el servidor donde corre la aplicación."
            ),
            que_hacer=(
                "Avise a quien administra la aplicación: esto no se arregla desde acá.",
                "Hay que revisar SUPABASE_URL y SUPABASE_KEY en las variables de entorno.",
                "Cuando le confirmen que ya están, presione Reintentar.",
            ),
            enlace=("Abrir el panel de Render", _PANEL_RENDER),
            reintentable=True,
        )

    if codigo in _TABLA_INEXISTENTE or codigo == _COLUMNA_INEXISTENTE:
        nombre = _nombre_que_falta(excepcion.message or "")
        numero = migracion_de(nombre.split(".")[-1]) if nombre else None
        detalle = f" ({nombre})" if nombre else ""
        pasos = ["Avise a quien administra la aplicación."]
        if numero:
            pasos.append(f"Falta aplicar la migración {numero} en el editor SQL de Supabase.")
        else:
            pasos.append("Falta aplicar una migración pendiente en el editor SQL de Supabase.")
        pasos.append("Cuando le confirmen que ya está, presione Reintentar.")
        panel = panel_de_supabase(supabase_url)
        return ErrorUsuario(
            codigo=BD_MIGRACION_FALTANTE,
            titulo="Falta una actualización en la base de datos",
            que_paso=(
                f"La aplicación buscó algo que todavía no existe en la base{detalle}. "
                "Es una actualización pendiente, no un dato perdido."
            ),
            que_hacer=tuple(pasos),
            enlace=("Abrir el editor SQL de Supabase", f"{panel}/sql") if panel else None,
            reintentable=True,
        )
    return None


def _nombre_que_falta(mensaje: str) -> str:
    """El nombre de la tabla o columna que el mensaje de Postgres señala.

    Tres formas según quién contesta: ``column carros.x does not exist`` (42703),
    ``relation "public.x" does not exist`` (42P01) y ``Could not find the table
    'public.x' in the schema cache`` (PGRST205).
    """
    for patron in (
        r"column ([\w.]+) does not exist",
        r"relation \"?([\w.]+)\"? does not exist",
        r"find the table '([\w.]+)'",
        r"'([\w.]+)' in the schema cache",
    ):
        encontrado = re.search(patron, mensaje, re.IGNORECASE)
        if encontrado:
            return encontrado.group(1).removeprefix("public.")
    return ""


def _archivo_no_reconocido(excepcion: ColumnasEcomFaltantes) -> ErrorUsuario:
    esperadas = ", ".join(excepcion.faltantes) or "las del informe de pedidos"
    encontradas = ", ".join(excepcion.encontradas[:8]) or "ninguna"
    return ErrorUsuario(
        codigo=ARCHIVO_NO_RECONOCIDO,
        titulo="El archivo no tiene el formato de ECOM",
        que_paso=(
            f"No se encontraron las columnas que necesita la aplicación ({esperadas}). "
            f"El archivo trae: {encontradas}."
        ),
        que_hacer=(
            "Verifique que descargó el informe de pedidos de ECOM y no otro reporte.",
            "Vuelva a subir el archivo correcto; no hace falta recargar la página.",
        ),
        reintentable=False,
    )


def _archivo_vacio() -> ErrorUsuario:
    return ErrorUsuario(
        codigo=ARCHIVO_VACIO,
        titulo="El archivo no trae pedidos",
        que_paso="El archivo se leyó bien, pero no tiene ninguna línea de pedido.",
        que_hacer=(
            "Si lo descargó muy temprano, vuelva a descargarlo después del corte.",
            "Suba el archivo nuevo acá mismo.",
        ),
        reintentable=False,
    )


def _archivo_de_otra_fecha(excepcion: SinPedidosEnLaFecha) -> ErrorUsuario:
    fecha = excepcion.fecha.isoformat() if excepcion.fecha else "la fecha pedida"
    return ErrorUsuario(
        codigo=ARCHIVO_FECHA,
        titulo="El archivo no trae pedidos de ese día",
        que_paso=(f"Se buscaron los pedidos del {fecha} y el archivo no tiene ninguno de ese día."),
        que_hacer=(
            "Revise que el archivo sea el del día que está planeando.",
            "Si descargó el de otro día, vuelva a descargar el correcto y súbalo.",
        ),
        reintentable=False,
    )
