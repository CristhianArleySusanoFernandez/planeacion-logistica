"""Pruebas de la clasificación de errores previsibles.

Cada caso construye la **excepción real** —la que lanza postgrest, httpx o el
lector— y no un doble con el texto a mano: el valor de este módulo es justamente
reconocer lo que llega de verdad, y un mock del mensaje no probaría nada.

El caso de control es el más importante: una excepción desconocida devuelve
``None`` y se propaga. Un clasificador que respondiera a todo esconderia los bugs.
"""

from datetime import date
from pathlib import Path

import httpx
import openpyxl
import pytest
from postgrest.exceptions import APIError

from planeacion.domain.errores import SinPedidosEnLaFecha, SinPedidosParaPivotear
from planeacion.infraestructura.adaptadores.entrada.web import errores
from planeacion.infraestructura.adaptadores.salida.excel.lector_ecom import (
    ColumnasEcomFaltantes,
    LectorEcomExcel,
)

_URL = "https://abcdefghijklmnop.supabase.co"


def _api_error(codigo: str, mensaje: str) -> APIError:
    return APIError({"code": codigo, "message": mensaje, "hint": "", "details": ""})


class TestSinConexion:
    def test_el_connect_error_de_httpx_se_reconoce(self) -> None:
        error = errores.clasificar(httpx.ConnectError("sin red"), _URL)

        assert error is not None
        assert error.codigo == errores.BD_SIN_CONEXION
        assert error.reintentable

    def test_tambien_los_timeouts_que_son_la_otra_cara_de_lo_mismo(self) -> None:
        for excepcion in (httpx.ConnectTimeout("lento"), httpx.ReadTimeout("lento")):
            error = errores.clasificar(excepcion, _URL)
            assert error is not None and error.codigo == errores.BD_SIN_CONEXION

    def test_el_enlace_sale_de_la_url_configurada(self) -> None:
        error = errores.clasificar(httpx.ConnectError("x"), _URL)

        assert error is not None and error.enlace is not None
        etiqueta, url = error.enlace
        assert url == "https://supabase.com/dashboard/project/abcdefghijklmnop"
        assert "Supabase" in etiqueta

    def test_sin_url_valida_no_hay_enlace_pero_si_instrucciones(self) -> None:
        """Mejor sin botón que con un botón que lleva a ninguna parte."""
        error = errores.clasificar(httpx.ConnectError("x"), "postgresql://local/db")

        assert error is not None
        assert error.enlace is None
        assert error.que_hacer


class TestCredenciales:
    def test_la_clave_rechazada_se_reconoce_por_el_mensaje(self) -> None:
        error = errores.clasificar(_api_error("", "Invalid API key"), _URL)

        assert error is not None
        assert error.codigo == errores.BD_CREDENCIALES
        assert error.enlace == ("Abrir el panel de Render", "https://dashboard.render.com")

    def test_tambien_por_el_codigo_de_postgrest(self) -> None:
        error = errores.clasificar(_api_error("PGRST301", "JWT expired"), _URL)

        assert error is not None and error.codigo == errores.BD_CREDENCIALES

    def test_el_texto_manda_a_avisar_porque_no_se_arregla_desde_la_app(self) -> None:
        error = errores.clasificar(_api_error("401", "unauthorized"), _URL)

        assert error is not None
        assert any("Avise" in paso for paso in error.que_hacer)


class TestMigracionFaltante:
    def test_la_tabla_inexistente_trae_el_numero_de_su_migracion(self) -> None:
        """42P01 sobre `parametros`: la crea la migración 005."""
        error = errores.clasificar(_api_error("42P01", 'relation "public.parametros" does not exist'), _URL)

        assert error is not None
        assert error.codigo == errores.BD_MIGRACION_FALTANTE
        assert any("005" in paso for paso in error.que_hacer)
        assert "parametros" in error.que_paso

    def test_el_codigo_de_postgrest_para_lo_mismo(self) -> None:
        error = errores.clasificar(
            _api_error("PGRST205", "Could not find the table 'public.carro_zonas' in the schema cache"),
            _URL,
        )

        assert error is not None
        assert error.codigo == errores.BD_MIGRACION_FALTANTE
        assert any("002" in paso for paso in error.que_hacer)  # la crea la 002

    def test_la_columna_inexistente_tambien_y_apunta_a_su_migracion(self) -> None:
        """42703 sobre `conductor_clave`: la agrega la 004."""
        error = errores.clasificar(_api_error("42703", "column carros.conductor_clave does not exist"), _URL)

        assert error is not None
        assert any("004" in paso for paso in error.que_hacer)

    def test_el_enlace_lleva_al_editor_sql(self) -> None:
        error = errores.clasificar(_api_error("42P01", 'relation "public.zonas" does not exist'), _URL)

        assert error is not None and error.enlace is not None
        assert error.enlace[1].endswith("/sql")

    def test_un_nombre_que_no_esta_en_ninguna_migracion_no_inventa_numero(self) -> None:
        error = errores.clasificar(
            _api_error("42P01", 'relation "public.tabla_inventada" does not exist'), _URL
        )

        assert error is not None
        assert not any(paso.count("migración ") and paso[-4:-1].isdigit() for paso in error.que_hacer)


class TestArchivos:
    def test_un_archivo_sin_las_columnas_dice_cuales_esperaba_y_cuales_trae(self, tmp_path: Path) -> None:
        """Se levanta la excepción leyendo un archivo de verdad, no a mano."""
        libro = openpyxl.Workbook()
        hoja = libro.active
        assert hoja is not None
        hoja.append(["Cliente", "Ciudad", "Otra cosa"])
        hoja.append(["200001", "TUNJA", "x"])
        ruta = tmp_path / "reporte_equivocado.xlsx"
        libro.save(ruta)

        with pytest.raises(ColumnasEcomFaltantes) as capturada:
            LectorEcomExcel().leer(ruta)
        error = errores.clasificar(capturada.value, _URL)

        assert error is not None
        assert error.codigo == errores.ARCHIVO_NO_RECONOCIDO
        assert not error.reintentable  # hay que subir otro archivo, no reintentar
        assert "Pedido" in error.que_paso  # lo que falta
        assert "Otra cosa" in error.que_paso  # lo que trae

    def test_el_archivo_sin_pedidos(self) -> None:
        error = errores.clasificar(SinPedidosParaPivotear("no trae líneas de pedido"), _URL)

        assert error is not None
        assert error.codigo == errores.ARCHIVO_VACIO
        assert any("después del corte" in paso for paso in error.que_hacer)

    def test_el_archivo_de_otro_dia_dice_que_fecha_se_buscaba(self) -> None:
        error = errores.clasificar(
            SinPedidosEnLaFecha("no trae pedidos con fecha", fecha=date(2026, 10, 7)), _URL
        )

        assert error is not None
        assert error.codigo == errores.ARCHIVO_FECHA
        assert "2026-10-07" in error.que_paso

    def test_la_fecha_se_clasifica_antes_que_el_vacio_aunque_sea_subclase(self) -> None:
        """`SinPedidosEnLaFecha` hereda de `SinPedidosParaPivotear`: si el orden
        estuviera al revés, el archivo de otro día diría "no trae pedidos"."""
        assert issubclass(SinPedidosEnLaFecha, SinPedidosParaPivotear)
        error = errores.clasificar(SinPedidosEnLaFecha("x", fecha=date(2026, 10, 7)), _URL)
        assert error is not None and error.codigo == errores.ARCHIVO_FECHA


class TestLoDesconocido:
    def test_una_excepcion_cualquiera_no_se_reconoce(self) -> None:
        """Y por eso se propaga: un panel para todo esconderia los bugs."""
        assert errores.clasificar(ValueError("algo raro"), _URL) is None

    def test_un_api_error_de_otra_cosa_tampoco(self) -> None:
        """Una violación de restricción no es ni permiso ni migración faltante."""
        assert errores.clasificar(_api_error("23505", "duplicate key value"), _URL) is None

    def test_un_error_de_dominio_que_no_es_de_archivo_tampoco(self) -> None:
        from planeacion.domain.errores import MovimientoInvalido

        assert errores.clasificar(MovimientoInvalido("no se puede mover"), _URL) is None


class TestPanelDeSupabase:
    def test_deriva_el_panel_de_la_url_del_proyecto(self) -> None:
        assert errores.panel_de_supabase("https://abc123.supabase.co") == (
            "https://supabase.com/dashboard/project/abc123"
        )

    def test_una_url_con_otra_forma_no_da_enlace(self) -> None:
        for url in ("", None, "https://example.com", "abc123.supabase.co"):
            assert errores.panel_de_supabase(url) is None


class TestMigracionDe:
    def test_encuentra_la_migracion_que_crea_la_tabla(self) -> None:
        assert errores.migracion_de("carro_zonas") == "002"
        assert errores.migracion_de("parametros") == "005"
        assert errores.migracion_de("clientes") == "001"

    def test_encuentra_la_que_agrega_una_columna(self) -> None:
        assert errores.migracion_de("lado_chiquinquira") == "004"

    def test_lo_que_no_esta_en_ninguna_devuelve_none(self) -> None:
        assert errores.migracion_de("tabla_inventada") is None
        assert errores.migracion_de("") is None
