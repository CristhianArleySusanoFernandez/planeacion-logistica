"""Pruebas del ECOM que llega como HTML con extensión .xls.

Lo que el portal de ECOM entrega no es un .xls binario: es una tabla HTML con el
nombre cambiado. Hay dos niveles de prueba: un HTML mínimo escrito a mano, para
fijar el comportamiento del parseo, y un **recorte del archivo real**
(`datos/ecom_html_recortado.xls`) para que el formato de verdad no se pueda
romper sin que una prueba avise. El recorte está anonimizado —documento, razón
social, nombre, dirección y teléfono son inventados— porque el repositorio no es
lugar para datos de clientes reales; el resto del archivo (etiquetas, atributos,
el `charset=us-ascii` que miente y los bytes cp1252) está tal cual.
"""

from pathlib import Path

import pytest

from planeacion.infraestructura.adaptadores.salida.excel.lector_ecom import (
    FormatoEcomInvalido,
    LectorEcomExcel,
    leer_filas_ecom,
)
from planeacion.infraestructura.adaptadores.salida.excel.lector_ecom_html import (
    filas_del_html,
    parece_html,
)

_RECORTE_REAL = Path(__file__).parent / "datos" / "ecom_html_recortado.xls"

_ENCABEZADOS = (
    "Tipo",
    "Pedido",
    "Est",
    "Fecha",
    "Hora",
    "Sku",
    "nit/ced",
    "R. Social",
    "Cliente",
    "Ciudad",
    "Barrio",
    "Zona",
    "Direccion",
    "Telefono",
    "Total",
    "Asesor",
)
_RESTO = ("No Compra", "Bodega", "Bodega Transf", "Observaciones", "Cod.Prod", "Producto", "Cantidad")
_FINAL = ("Unidad", "Inventario", "Rotacion", "Precio U.", "Descuento", "Descuento_2", "Iva", "Total")


def _html(filas: list[tuple[str, ...]], envoltorio: str = "") -> str:
    """Un HTML mínimo con las columnas que el mapeo necesita, en su orden real."""
    encabezado = _ENCABEZADOS + _RESTO + _FINAL + ("", "Tip Pro", "Comentario", "Kilos")
    partes = ["<html><head><meta charset=us-ascii></head><body>", envoltorio, "<table>"]
    partes.append("<tr>" + "".join(f"<td>{celda}</td>" for celda in encabezado) + "</tr>")
    for fila in filas:
        partes.append("<tr>" + "".join(f"<td>{celda}</td>" for celda in fila) + "</tr>")
    partes.append("</table></body></html>")
    return "".join(partes)


def _fila(pedido: str, cliente: str, total: str, kilos: str, fecha: str = "2026-10-07") -> tuple[str, ...]:
    relleno_inicial = ("PEDIDO", pedido, "Sin Descargar", fecha, "05:02:15", "4", "1054093788", "", cliente)
    medio = ("15001 - TUNJA", "CENTRO", "", "CL 1 2 3", "3000000000", total, "10954-ASESOR")
    resto = ("-", "01-TUNJA", "-", "", "1011172", "CAFE 500G", "1")
    final = ("UN", "", "", "11294", "0.00", "", "19.00", total)
    return relleno_inicial + medio + resto + final + ("", "N", "", kilos)


def _escribir(ruta: Path, contenido: str, codificacion: str = "cp1252") -> Path:
    ruta.write_bytes(contenido.encode(codificacion))
    return ruta


class TestDeteccion:
    def test_reconoce_el_html_aunque_se_llame_xls(self, tmp_path: Path) -> None:
        ruta = _escribir(tmp_path / "infpedidos.xls", _html([]))

        assert parece_html(ruta)

    def test_reconoce_el_arranque_con_sangria_del_archivo_real(self, tmp_path: Path) -> None:
        """El real empieza con cuatro tabulaciones antes del <html>."""
        ruta = _escribir(tmp_path / "infpedidos.xls", "\t\t\t\t" + _html([]))

        assert parece_html(ruta)

    def test_un_xls_binario_de_verdad_no_es_html(self, tmp_path: Path) -> None:
        ruta = tmp_path / "viejo.xls"
        ruta.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 100)  # firma OLE2

        assert not parece_html(ruta)

    def test_el_recorte_real_se_reconoce(self) -> None:
        assert parece_html(_RECORTE_REAL)


class TestParseo:
    def test_lee_una_linea_con_la_misma_semantica_que_el_xlsx(self, tmp_path: Path) -> None:
        """Los kilos vienen en GRAMOS, como en todo origen de ECOM."""
        ruta = _escribir(
            tmp_path / "infpedidos.xls",
            _html([_fila("6006023", "200001651668-DEISY CUERVO", "13439.86", "600")]),
        )

        lineas = LectorEcomExcel().leer(ruta)

        assert len(lineas) == 1
        linea = lineas[0]
        assert linea.pedido == "6006023"
        assert linea.codigo_cliente == "200001651668"
        assert linea.nombre_cliente == "DEISY CUERVO"
        assert str(linea.total_linea) == "13439.86"
        assert str(linea.kilos) == "0.6"
        assert linea.fecha is not None and linea.fecha.isoformat() == "2026-10-07"

    def test_las_etiquetas_dentro_de_la_celda_no_parten_el_valor(self, tmp_path: Path) -> None:
        """Excel mete <font>/<span> adentro de los <td>; el valor es uno solo."""
        html = _html([_fila("6006023", "200001651668-DEISY CUERVO", "13439.86", "600")])
        html = html.replace(
            "<td>200001651668-DEISY CUERVO</td>",
            "<td><font face=Arial>200001651668-<span>DEISY CUERVO</span></font></td>",
        )
        ruta = _escribir(tmp_path / "infpedidos.xls", html)

        lineas = LectorEcomExcel().leer(ruta)

        assert lineas[0].codigo_cliente == "200001651668"
        assert lineas[0].nombre_cliente == "DEISY CUERVO"

    def test_los_acentos_sobreviven_aunque_el_archivo_declare_us_ascii(self, tmp_path: Path) -> None:
        """El charset del encabezado miente: los bytes son cp1252."""
        ruta = _escribir(
            tmp_path / "infpedidos.xls", _html([_fila("1", "200001651668-PEÑA LUENGAS", "100", "10")])
        )

        assert LectorEcomExcel().leer(ruta)[0].nombre_cliente == "PEÑA LUENGAS"

    def test_de_varias_tablas_gana_la_de_los_datos(self, tmp_path: Path) -> None:
        """Los exports envuelven la tabla real en tablas de maqueta."""
        maqueta = "<table><tr><td>Informe de pedidos</td></tr></table>"
        ruta = _escribir(
            tmp_path / "infpedidos.xls",
            _html(
                [_fila("1", "200001651668-UNO", "100", "10"), _fila("2", "200001651669-DOS", "200", "20")],
                envoltorio=maqueta,
            ),
        )

        assert [linea.pedido for linea in LectorEcomExcel().leer(ruta)] == ["1", "2"]

    def test_un_html_sin_filas_avisa_en_vez_de_fallar_raro(self, tmp_path: Path) -> None:
        ruta = _escribir(tmp_path / "infpedidos.xls", "<html><body><p>Sin resultados</p></body></html>")

        with pytest.raises(FormatoEcomInvalido, match="no encontré ninguna fila"):
            filas_del_html(ruta)

    def test_las_filas_crudas_mapean_con_el_lector_de_siempre(self, tmp_path: Path) -> None:
        """Lo que este módulo devuelve son filas: el mapeo de columnas es el único
        que hay, no una copia. Y no pasa por openpyxl, que costaba 1,5 s por
        archivo solo para volver a recorrer lo mismo."""
        ruta = _escribir(tmp_path / "infpedidos.xls", _html([_fila("1", "200001651668-UNO", "100", "10")]))

        filas = filas_del_html(ruta)

        assert filas[0][1] == "Pedido"  # la primera fila es el encabezado
        assert leer_filas_ecom(filas, ruta.name)[0].pedido == "1"


class TestRecorteDelArchivoReal:
    def test_lee_el_pedido_completo_del_archivo_real(self) -> None:
        lineas = LectorEcomExcel().leer(_RECORTE_REAL)

        assert len(lineas) == 4  # un pedido con cuatro líneas de producto
        assert {linea.pedido for linea in lineas} == {"6006023"}
        assert {linea.fecha.isoformat() for linea in lineas if linea.fecha} == {"2026-10-07"}

    def test_las_filas_de_continuacion_dejan_vacios_los_datos_del_cliente(self) -> None:
        """Así viene el real: ciudad y barrio solo en la primera línea del pedido."""
        lineas = LectorEcomExcel().leer(_RECORTE_REAL)

        assert lineas[0].ciudad == "15407 - VILLA DE LEYVA"
        assert [linea.ciudad for linea in lineas[1:]] == [None, None, None]
        # El código de cliente sí se repite en todas, que es lo que permite agrupar.
        assert {linea.codigo_cliente for linea in lineas} == {"200009999991"}

    def test_los_totales_y_los_kilos_del_archivo_real_se_convierten(self) -> None:
        lineas = LectorEcomExcel().leer(_RECORTE_REAL)

        assert [str(linea.total_linea) for linea in lineas] == [
            "13439.86",
            "15128.40",
            "4995.90",
            "27982.85",
        ]
        assert [str(linea.kilos) for linea in lineas] == ["0.6", "0.39", "0.11", "0.9"]
