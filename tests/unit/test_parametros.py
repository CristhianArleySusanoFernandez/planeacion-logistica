"""Pruebas del catálogo de parámetros y de su traducción a/desde Supabase.

Lo que importa acá es la red: la app tiene que funcionar con la tabla vacía, con
una clave faltante o con la migración sin aplicar. Un parámetro que vuelva en
cero apagaría una variable del equilibrio en silencio.
"""

from decimal import Decimal

import pytest

from planeacion.domain.modelo import CATALOGO, DEFECTOS, Parametros
from planeacion.domain.modelo.balanceo import REGLAS_POR_DEFECTO
from planeacion.domain.modelo.parametros import (
    CLAVE_KILOS_MAX_POR_UNIDAD,
    CLAVE_MIN_CLIENTES_CONDUCTOR,
    CLAVE_W_CLIENTES,
    CLAVE_W_KILOS,
)
from planeacion.infraestructura.adaptadores.salida.supabase import repositorio_parametros


class TestCatalogo:
    def test_todas_las_claves_tienen_default_y_descripcion(self) -> None:
        assert len(CATALOGO) == len(DEFECTOS) == 8
        for definicion in CATALOGO:
            assert definicion.descripcion.strip(), definicion.clave
            assert definicion.valor_por_defecto >= 0

    def test_los_defaults_de_los_pesos_son_los_del_dominio(self) -> None:
        """Una sola fuente de verdad: si cambia `ReglasBalanceo`, cambia el catálogo."""
        assert DEFECTOS[CLAVE_W_CLIENTES] == Decimal(str(REGLAS_POR_DEFECTO.w_clientes))
        assert DEFECTOS[CLAVE_W_KILOS] == Decimal(str(REGLAS_POR_DEFECTO.w_kilos))


class TestLecturaConRed:
    def test_sin_nada_guardado_rigen_los_defaults(self) -> None:
        """Base sin migrar: la app tiene que andar igual."""
        parametros = Parametros(valores={})

        assert parametros.reglas_balanceo() == REGLAS_POR_DEFECTO
        assert parametros.entero(CLAVE_MIN_CLIENTES_CONDUCTOR) == 50

    def test_una_clave_que_falta_cae_en_su_default(self) -> None:
        """Si alguien borra una fila, no puede quedar un cero silencioso."""
        parametros = Parametros(valores={CLAVE_W_KILOS: Decimal("0.25")})

        assert parametros.flotante(CLAVE_W_KILOS) == 0.25
        assert parametros.flotante(CLAVE_W_CLIENTES) == REGLAS_POR_DEFECTO.w_clientes

    def test_los_valores_guardados_llegan_a_las_reglas(self) -> None:
        parametros = Parametros(valores={CLAVE_W_KILOS: Decimal("0"), CLAVE_W_CLIENTES: Decimal("0.8")})

        reglas = parametros.reglas_balanceo()

        assert (reglas.w_kilos, reglas.w_clientes) == (0.0, 0.8)

    def test_un_cero_explicito_se_respeta(self) -> None:
        """Apagar una variable es una decisión válida y no se puede confundir con
        la ausencia de la clave."""
        assert Parametros(valores={CLAVE_W_KILOS: Decimal("0")}).flotante(CLAVE_W_KILOS) == 0.0

    def test_entero_corta_el_decimal_que_trae_la_columna_numeric(self) -> None:
        parametros = Parametros(valores={CLAVE_MIN_CLIENTES_CONDUCTOR: Decimal("50.0000")})

        assert parametros.entero(CLAVE_MIN_CLIENTES_CONDUCTOR) == 50

    def test_el_techo_de_kilos_sale_del_catalogo(self) -> None:
        assert Parametros().numero(CLAVE_KILOS_MAX_POR_UNIDAD) == Decimal("25")


class TestTraduccionSupabase:
    def test_la_fila_vuelve_como_clave_y_decimal(self) -> None:
        clave, valor = repositorio_parametros.desde_fila({"clave": "w_kilos", "valor": "0.5000"})

        assert (clave, valor) == ("w_kilos", Decimal("0.5000"))

    def test_los_pesos_no_se_leen_como_float(self) -> None:
        """La columna es numeric: convertirla por float perdería precisión antes
        de que el dominio decida qué hacer con ella."""
        _, valor = repositorio_parametros.desde_fila({"clave": "w_pesos", "valor": "0.3"})

        assert isinstance(valor, Decimal)


class TestGuardadoValidado:
    def test_una_clave_fuera_del_catalogo_no_se_guarda(self) -> None:
        """Una fila escrita a mano en Supabase con un nombre inventado no tiene
        quién la lea: mejor fallar al guardarla que dejarla ahí."""
        repositorio = repositorio_parametros.RepositorioParametrosSupabase(cliente=None)  # type: ignore[arg-type]

        with pytest.raises(LookupError, match="no existe en el catálogo"):
            repositorio.guardar("w_inventado", Decimal("1"))
