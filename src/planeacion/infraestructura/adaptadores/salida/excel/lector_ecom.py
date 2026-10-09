"""Lector del archivo ECOM crudo diario (.xlsx): una fila por línea de producto.

Solo traducción de datos (fila → LineaPedido); la zona NO viene en este archivo.
ECOM cambia detalles del export sin avisar, así que el lector es tolerante:
- La hoja NO se busca por nombre fijo ("Hoja1", "Informe"...): si el libro tiene
  una sola hoja se usa esa; con varias, la primera cuyo encabezado traiga las
  columnas esenciales.
- Las columnas se identifican por el TEXTO de su encabezado (con sinónimos y
  normalización), no por posición fija: agregar, quitar o reordenar columnas
  no rompe el lector mientras existan las que necesita.
Peculiaridades del formato real:
- Los pedidos multilínea traen R. Social y Total de factura solo en la primera
  línea; Cliente viene siempre → el código se saca de Cliente con fallback a
  R. Social.
- Hay DOS columnas "Total": la de la factura (zona de cabecera del pedido) y la
  de la línea (zona de producto, tras "Iva"). Ver ``_mapear_columnas``.
- Los totales vienen como texto (a veces con separador de miles ',').
- La columna "Kilos" viene en gramos: aquí se convierte a kilos.
- La fecha puede venir dañada como texto serial (p.ej. '46190') → queda None.
- La hoja declara dimensiones falsas: se corta tras una racha de filas sin pedido.
"""

import logging
import unicodedata
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import openpyxl
from openpyxl.utils import get_column_letter
from openpyxl.workbook import Workbook
from openpyxl.worksheet.worksheet import Worksheet

from planeacion.domain.modelo import LineaPedido

_logger = logging.getLogger(__name__)

_MAX_FILAS_VACIAS_SEGUIDAS = 100
_GRAMOS_POR_KILO = Decimal("1000")

# Sinónimos aceptados por columna lógica, ya normalizados (ver normalizar_encabezado).
# Las columnas "total" no van aquí: se resuelven aparte por posición relativa
# porque el archivo trae dos con el mismo nombre (ver _mapear_columnas).
_SINONIMOS: dict[str, tuple[str, ...]] = {
    "pedido": ("pedido",),
    "fecha": ("fecha",),
    "documento": ("nit/ced", "nit", "documento"),
    "razon_social": ("r. social", "razon social", "r.social"),
    "cliente": ("cliente",),
    "ciudad": ("ciudad",),
    "barrio": ("barrio",),
    "direccion": ("direccion",),
    "asesor": ("asesor",),
    "producto": ("producto",),
    "cod_producto": ("cod.prod", "cod prod", "codigo producto"),
    "cantidad": ("cantidad",),
    "kilos": ("kilos",),
}

# Nombre con el que cada columna lógica se menciona en mensajes y avisos.
_NOMBRE_VISIBLE: dict[str, str] = {
    "pedido": "Pedido",
    "fecha": "Fecha",
    "documento": "nit/ced",
    "razon_social": "R. Social",
    "cliente": "Cliente",
    "ciudad": "Ciudad",
    "barrio": "Barrio",
    "direccion": "Direccion",
    "asesor": "Asesor",
    "producto": "Producto",
    "cod_producto": "Cod.Prod",
    "cantidad": "Cantidad",
    "kilos": "Kilos",
    "total_linea": "Total (de la línea)",
}


class FormatoEcomInvalido(Exception):
    """Una celda del ECOM no se puede interpretar (el mensaje ubica la fila)."""


class ColumnasEcomFaltantes(FormatoEcomInvalido):
    """Al archivo le faltan columnas esenciales; el mensaje dice cuáles."""


@dataclass(frozen=True)
class _MapaColumnas:
    """Índices 0-based de cada columna lógica en la hoja (None = no vino)."""

    pedido: int
    fecha: int
    total_linea: int
    kilos: int
    cliente: int | None
    razon_social: int | None
    documento: int | None
    ciudad: int | None
    barrio: int | None
    direccion: int | None
    asesor: int | None
    producto: int | None
    cod_producto: int | None
    cantidad: int | None
    total_factura: int | None

    @property
    def max_col(self) -> int:
        """Última columna (1-based) que hace falta leer de cada fila."""
        indices = [
            self.pedido, self.fecha, self.total_linea, self.kilos,
            self.cliente, self.razon_social, self.documento, self.ciudad,
            self.barrio, self.direccion, self.asesor, self.producto,
            self.cod_producto, self.cantidad, self.total_factura,
        ]  # fmt: skip
        return max(indice for indice in indices if indice is not None) + 1


def normalizar_encabezado(valor: Any) -> str:
    """Encabezado → forma comparable: minúsculas, sin acentos, espacios colapsados."""
    texto = "" if valor is None else str(valor)
    sin_acentos = "".join(
        caracter for caracter in unicodedata.normalize("NFD", texto) if not unicodedata.combining(caracter)
    )
    return " ".join(sin_acentos.lower().split())


def _resolver_totales(normalizados: Sequence[str]) -> tuple[int | None, int | None]:
    """(total_factura, total_linea) entre las columnas llamadas "Total".

    El archivo trae dos "Total": el de la factura (en la zona de cabecera del
    pedido) y el de la línea (en la zona de producto, justo después de "Iva").
    Heurística: si hay columna "Iva", el primer "Total" DESPUÉS de "Iva" es el
    de línea y el primero antes el de factura; sin "Iva", el primero es factura
    y el segundo línea. Los archivos viejos traían el de línea renombrado como
    "Total2": se acepta como sinónimo directo.
    """
    posiciones_total = [i for i, texto in enumerate(normalizados) if texto == "total"]
    total2 = next((i for i, texto in enumerate(normalizados) if texto == "total2"), None)
    iva = next((i for i, texto in enumerate(normalizados) if texto == "iva"), None)

    linea = total2
    if linea is None and iva is not None:
        linea = next((i for i in posiciones_total if i > iva), None)
    if linea is None and len(posiciones_total) >= 2:
        linea = posiciones_total[1]
    factura = next((i for i in posiciones_total if i != linea), None)
    return factura, linea


def _mapear_columnas(encabezados: Sequence[Any]) -> _MapaColumnas:
    """Fila de encabezados → mapa de columnas lógicas; falla listando lo que falta."""
    normalizados = [normalizar_encabezado(celda) for celda in encabezados]
    indices: dict[str, int | None] = {
        nombre: next((i for i, texto in enumerate(normalizados) if texto in sinonimos), None)
        for nombre, sinonimos in _SINONIMOS.items()
    }
    total_factura, total_linea = _resolver_totales(normalizados)

    faltantes = [
        _NOMBRE_VISIBLE[nombre] for nombre in ("pedido", "fecha", "kilos") if indices[nombre] is None
    ]
    if indices["cliente"] is None and indices["razon_social"] is None:
        faltantes.append(_NOMBRE_VISIBLE["cliente"])
    if total_linea is None:
        faltantes.append(_NOMBRE_VISIBLE["total_linea"])
    if faltantes:
        encontrados = ", ".join(str(celda).strip() for celda in encabezados if normalizar_encabezado(celda))
        raise ColumnasEcomFaltantes(
            f"No pude leer el archivo de ECOM: faltan las columnas [{', '.join(faltantes)}].\n"
            f"Encabezados encontrados: {encontrados or '(ninguno)'}.\n"
            "¿El archivo es un export de pedidos de ECOM?"
        )

    opcionales_ausentes = [
        _NOMBRE_VISIBLE[nombre]
        for nombre in (
            "documento",
            "ciudad",
            "barrio",
            "direccion",
            "asesor",
            "producto",
            "cod_producto",
            "cantidad",
        )
        if indices[nombre] is None
    ]
    if opcionales_ausentes:
        _logger.warning(
            "El ECOM no trae las columnas opcionales %s: esos campos quedan vacíos.",
            ", ".join(opcionales_ausentes),
        )

    # Los esenciales ya se validaron arriba; mypy no sigue esa prueba.
    assert indices["pedido"] is not None and indices["fecha"] is not None
    assert indices["kilos"] is not None and total_linea is not None
    return _MapaColumnas(
        pedido=indices["pedido"],
        fecha=indices["fecha"],
        total_linea=total_linea,
        kilos=indices["kilos"],
        cliente=indices["cliente"],
        razon_social=indices["razon_social"],
        documento=indices["documento"],
        ciudad=indices["ciudad"],
        barrio=indices["barrio"],
        direccion=indices["direccion"],
        asesor=indices["asesor"],
        producto=indices["producto"],
        cod_producto=indices["cod_producto"],
        cantidad=indices["cantidad"],
        total_factura=total_factura,
    )


def _encabezados_de(hoja: Worksheet, columna_inicial: int = 0) -> Sequence[Any]:
    """Fila 1 de la hoja desde ``columna_inicial`` (0-based).

    El desplazamiento existe porque el mismo bloque de ECOM aparece pegado a la
    derecha de otros datos dentro de la hoja PEDIDOS de los .xlsm (ver
    ``lector_ecom_embebido``): rebanar desde ahí deja el mapeo por encabezado
    intacto y evita que columnas homónimas de la izquierda ganen el match.
    """
    fila = next(hoja.iter_rows(min_row=1, max_row=1, values_only=True), ())
    return fila[columna_inicial:]


def _elegir_hoja(libro: Workbook, nombre_archivo: str) -> tuple[Worksheet, _MapaColumnas]:
    """Con una sola hoja, esa; con varias, la primera cuyo encabezado mapee."""
    if len(libro.sheetnames) == 1:
        hoja = libro[libro.sheetnames[0]]
        return hoja, _mapear_columnas(_encabezados_de(hoja))

    primer_error: ColumnasEcomFaltantes | None = None
    for nombre in libro.sheetnames:
        hoja = libro[nombre]
        try:
            return hoja, _mapear_columnas(_encabezados_de(hoja))
        except ColumnasEcomFaltantes as error:
            primer_error = primer_error or error
    assert primer_error is not None
    raise ColumnasEcomFaltantes(
        f"Ninguna hoja de {nombre_archivo} ({', '.join(libro.sheetnames)}) trae las "
        f"columnas de un export de pedidos de ECOM. Del primer intento: {primer_error}"
    )


def _texto(valor: Any) -> str | None:
    """Celda → texto limpio. Los enteros que Excel guarda como float no llevan '.0'."""
    if valor is None:
        return None
    if isinstance(valor, float) and valor.is_integer():
        valor = int(valor)
    texto = str(valor).strip()
    return texto or None


def convertir_decimal(valor: Any, contexto: str = "") -> Decimal:
    """Texto/número → Decimal. Vacío vale 0; tolera separador de miles ','."""
    texto = _texto(valor)
    if texto is None:
        return Decimal("0")
    try:
        return Decimal(texto.replace(",", ""))
    except InvalidOperation as error:
        raise FormatoEcomInvalido(f"valor no numérico {texto!r} {contexto}".strip()) from error


def extraer_codigo_cliente(texto_cliente: str) -> str:
    """De "CODIGO-NOMBRE" toma el prefijo antes del primer '-'."""
    return texto_cliente.split("-", 1)[0].strip()


def _nombre_cliente(texto_cliente: str) -> str | None:
    partes = texto_cliente.split("-", 1)
    if len(partes) < 2:
        return None
    return partes[1].strip() or None


def convertir_fecha(valor: Any) -> date | None:
    """datetime/date → date; texto ISO se intenta; lo dañado (p.ej. '46190') → None."""
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    texto = _texto(valor)
    if texto is None:
        return None
    try:
        return datetime.fromisoformat(texto).date()
    except ValueError:
        return None


def leer_libro_ecom(libro: Workbook, nombre_archivo: str) -> list[LineaPedido]:
    """Libro ya abierto → líneas de pedido, eligiendo la hoja por su encabezado.

    Es el punto de entrada que comparte todo origen que termine en un libro de
    openpyxl: el .xlsx/.xlsm que abre ``LectorEcomExcel`` y el .xls binario que
    ``lector_ecom_xls`` traduce a uno en memoria. Así el mapeo de columnas y el
    parseo de celdas viven en un solo lugar.
    """
    hoja, mapa = _elegir_hoja(libro, nombre_archivo)
    _logger.info("Leyendo pedidos de la hoja %r de %s", hoja.title, nombre_archivo)
    return list(_lineas_de_hoja(hoja, mapa))


def leer_filas_ecom(filas: Sequence[Sequence[Any]], nombre_archivo: str) -> list[LineaPedido]:
    """Filas crudas (la primera es el encabezado) → líneas de pedido.

    Mismo mapeo por encabezado y mismo parseo de celdas que cualquier otro
    origen; lo único que cambia es de dónde salen las filas. Lo usa el lector de
    HTML, que las tiene ya en memoria y no necesita un libro de openpyxl.
    """
    if not filas:
        raise FormatoEcomInvalido(f"{nombre_archivo} no trae ninguna fila")
    mapa = _mapear_columnas(filas[0])
    _logger.info("Leyendo pedidos de %s (%d filas)", nombre_archivo, len(filas))
    return list(_leer_lineas(filas[1:], mapa))


class LectorEcomExcel:
    """Adaptador del puerto ``LectorDePedidos``.

    Acepta las tres extensiones que llegan del ECOM. ``.xlsx`` y ``.xlsm`` son
    el mismo OOXML (el segundo solo agrega macros) y openpyxl los abre igual.
    Un ``.xls`` puede ser dos cosas distintas y se decide por el CONTENIDO, no
    por el nombre: el binario viejo BIFF va al traductor de ``lector_ecom_xls``,
    y la tabla HTML que el portal de ECOM entrega con ese nombre va al de
    ``lector_ecom_html``. Los dos devuelven el mismo libro en memoria.
    """

    def leer(self, ruta: Path) -> list[LineaPedido]:
        if ruta.suffix.lower() == ".xls":
            # Imports locales a propósito: los dos traductores importan los
            # errores de este módulo, así que a nivel de módulo el ciclo no
            # cerraría.
            from planeacion.infraestructura.adaptadores.salida.excel.lector_ecom_html import (
                filas_del_html,
                parece_html,
            )
            from planeacion.infraestructura.adaptadores.salida.excel.lector_ecom_xls import (
                abrir_xls_como_libro,
            )

            if parece_html(ruta):
                # El HTML no pasa por openpyxl: sus filas van derecho al mapeo.
                return leer_filas_ecom(filas_del_html(ruta), ruta.name)
            libro = abrir_xls_como_libro(ruta)
        else:
            libro = openpyxl.load_workbook(ruta, read_only=True, data_only=True)
        try:
            return leer_libro_ecom(libro, ruta.name)
        finally:
            libro.close()


def _celda(fila: Sequence[Any], indice: int | None) -> Any:
    if indice is None or indice >= len(fila):
        return None
    return fila[indice]


def _letra(indice: int) -> str:
    return get_column_letter(indice + 1)


def _lineas_de_hoja(hoja: Worksheet, mapa: _MapaColumnas, columna_inicial: int = 0) -> Iterator[LineaPedido]:
    """Las filas de datos de una hoja de openpyxl, ya rebanadas desde ``columna_inicial``."""
    yield from _leer_lineas(
        hoja.iter_rows(
            min_row=2,
            min_col=columna_inicial + 1,
            max_col=columna_inicial + mapa.max_col,
            values_only=True,
        ),
        mapa,
        columna_inicial,
    )


def _leer_lineas(
    filas: Iterable[Sequence[Any]], mapa: _MapaColumnas, columna_inicial: int = 0
) -> Iterator[LineaPedido]:
    """Filas de datos → LineaPedido. Los índices de ``mapa`` son relativos a
    ``columna_inicial``, así que las filas llegan ya rebanadas desde ahí.

    Toma un iterable de filas y no una hoja para que el origen pueda ser
    cualquiera: una hoja de openpyxl o la tabla HTML parseada, que así no tiene
    que construir un libro intermedio solo para que lo recorramos de vuelta
    (eran 1,5 de los 3,7 s que costaba leer el ECOM del 7 de octubre).
    """
    vacias_seguidas = 0
    for numero, fila in enumerate(filas, start=2):
        pedido = _texto(_celda(fila, mapa.pedido))
        if pedido is None:
            vacias_seguidas += 1
            if vacias_seguidas > _MAX_FILAS_VACIAS_SEGUIDAS:
                return
            continue
        vacias_seguidas = 0
        cliente_crudo = _texto(_celda(fila, mapa.cliente)) or _texto(_celda(fila, mapa.razon_social))
        if cliente_crudo is None:
            raise FormatoEcomInvalido(f"fila {numero}: sin cliente (Cliente y R. Social vacías)")
        cantidad_cruda = _celda(fila, mapa.cantidad)
        # Las letras de los mensajes se corrigen con el desplazamiento para que
        # señalen la columna real de la hoja, no la del bloque rebanado.
        yield LineaPedido(
            pedido=pedido,
            codigo_cliente=extraer_codigo_cliente(cliente_crudo),
            fecha=convertir_fecha(_celda(fila, mapa.fecha)),
            total_linea=convertir_decimal(
                _celda(fila, mapa.total_linea),
                f"(fila {numero}, col {_letra(mapa.total_linea + columna_inicial)})",
            ),
            kilos=convertir_decimal(
                _celda(fila, mapa.kilos), f"(fila {numero}, col {_letra(mapa.kilos + columna_inicial)})"
            )
            / _GRAMOS_POR_KILO,
            nombre_cliente=_nombre_cliente(cliente_crudo),
            documento=_texto(_celda(fila, mapa.documento)),
            direccion=_texto(_celda(fila, mapa.direccion)),
            ciudad=_texto(_celda(fila, mapa.ciudad)),
            barrio=_texto(_celda(fila, mapa.barrio)),
            producto=_texto(_celda(fila, mapa.producto)),
            cod_producto=_texto(_celda(fila, mapa.cod_producto)),
            cantidad=(
                convertir_decimal(
                    cantidad_cruda,
                    f"(fila {numero}, col {_letra((mapa.cantidad or 0) + columna_inicial)})",
                )
                if _texto(cantidad_cruda) is not None
                else None
            ),
            asesor=_texto(_celda(fila, mapa.asesor)),
        )


def leer_bloque_ecom(hoja: Worksheet, columna_inicial: int = 0) -> list[LineaPedido]:
    """Lee un bloque de ECOM dentro de una hoja, mapeando su encabezado desde
    ``columna_inicial`` (0-based).

    Es el punto de entrada que comparten los dos orígenes del mismo formato: el
    .xlsx suelto de ECOM (bloque en la columna A) y la copia pegada en la hoja
    PEDIDOS de los .xlsm de planeación (bloque en la S).
    """
    mapa = _mapear_columnas(_encabezados_de(hoja, columna_inicial))
    return list(_lineas_de_hoja(hoja, mapa, columna_inicial))
