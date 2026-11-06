"""Pruebas del Balanceador con zonas especiales.

Una **zona especial** es un cliente que pide de vez en cuando y en grande, y que
la operación despacha aparte con el vehículo que convenga ese día: COMFABOY,
IMPACTA, PIZZA NOSTRA, MEDELLIN y una decena más. No tienen carro de costumbre,
así que **no tienen repertorio**, y por eso aparecían todos los días en el aviso
de "zonas sin carro" —ruido— o, cuando pedían, quedaban sin asignar: el 27 de
octubre de 2026 COMFABOY fue la única zona que la app no pudo repartir.

Con la marca puesta son elegibles en **cualquier ruta de su pool** y el
balanceador las coloca por carga. Eso es la sugerencia de vehículo que pidió la
operación: no es una excepción al balanceo, es balanceo sin repertorio.

La fuente de la marca es **`zonas.especial`** y nada más: ni una lista en el
código, ni el nombre. Se edita en Configuración → Zonas.
"""

from dataclasses import replace
from decimal import Decimal

import pytest

from planeacion.domain.errores import MovimientoInvalido
from planeacion.domain.modelo import (
    NOMBRES_ESPECIALES,
    Carro,
    ReglaChiquinquira,
    ReglasBalanceo,
    ResultadoBalanceo,
    ZonaAgregada,
)
from planeacion.domain.servicios.balanceador import AjustadorDeAsignacion, Balanceador
from planeacion.domain.servicios.parseo_zonas import crear_zona

SIN_MEJORA = ReglasBalanceo(max_iteraciones=0)


def _zona(nombre: str, clientes: int, pesos: str, *, especial: bool = False) -> ZonaAgregada:
    return ZonaAgregada(
        zona=replace(crear_zona(nombre), especial=especial),
        facturas=clientes,
        clientes=clientes,
        pesos=Decimal(pesos),
        kilos=Decimal("1"),
    )


def _carro_de(resultado: ResultadoBalanceo, nombre_zona: str) -> str | None:
    for cargas in resultado.cargas_por_municipio.values():
        for carga in cargas:
            if any(zona.zona.nombre == nombre_zona for zona in carga.zonas):
                return carga.carro.numero
    return None


class TestElegibleEnTodoSuPool:
    _CARROS = {"TUNJA": [Carro(numero="18"), Carro(numero="19"), Carro(numero="20")]}

    def test_una_especial_sin_repertorio_se_asigna_igual(self) -> None:
        """El caso de COMFABOY el 27 de octubre: antes quedaba sin asignar."""
        zonas = [_zona("(TUNJA): COMFABOY", 1, "5000000", especial=True)]
        repertorio = {"18": {"(TUNJA): OTRA"}}

        resultado = Balanceador().balancear(zonas, self._CARROS, None, SIN_MEJORA, repertorio)

        assert _carro_de(resultado, "(TUNJA): COMFABOY") is not None
        assert resultado.zonas_sin_carro == []

    def test_una_zona_normal_sin_repertorio_sigue_quedando_sin_carro(self) -> None:
        """La regresión que importa: la marca no relaja nada para las demás."""
        zonas = [_zona("(TUNJA): SIN CONFIGURAR", 1, "5000000")]
        repertorio = {"18": {"(TUNJA): OTRA"}}

        resultado = Balanceador().balancear(zonas, self._CARROS, None, SIN_MEJORA, repertorio)

        assert [zona.zona.nombre for zona in resultado.zonas_sin_carro] == ["(TUNJA): SIN CONFIGURAR"]

    def test_la_especial_va_al_carro_menos_cargado_de_su_pool(self) -> None:
        """La sugerencia de vehículo es el balanceo: el que tiene menos carga."""
        zonas = [
            _zona("(TUNJA): GRANDE", 100, "90000000"),
            _zona("(TUNJA): MEDIANA", 50, "40000000"),
            _zona("(TUNJA): IMPACTA", 1, "1000000", especial=True),
        ]
        repertorio = {"18": {"(TUNJA): GRANDE"}, "19": {"(TUNJA): MEDIANA"}}

        resultado = Balanceador().balancear(zonas, self._CARROS, None, SIN_MEJORA, repertorio)

        # 18 lleva 90 millones y 19 lleva 40: la especial va al 20, que va vacío.
        assert _carro_de(resultado, "(TUNJA): IMPACTA") == "20"

    def test_el_repertorio_de_la_especial_no_la_limita(self) -> None:
        """Puede tener pares viejos de cuando se sembraba; no la encierran."""
        zonas = [
            _zona("(TUNJA): GRANDE", 100, "90000000"),
            _zona("(TUNJA): IMPACTA", 1, "1000000", especial=True),
        ]
        # El repertorio dice que solo el 18 la atiende, y el 18 va cargadísimo.
        repertorio = {"18": {"(TUNJA): GRANDE", "(TUNJA): IMPACTA"}}

        resultado = Balanceador().balancear(zonas, self._CARROS, None, SIN_MEJORA, repertorio)

        assert _carro_de(resultado, "(TUNJA): IMPACTA") != "18"

    def test_sin_ninguna_ruta_en_su_pool_queda_sin_carro(self) -> None:
        """Ser especial no inventa vehículos donde no hay."""
        zonas = [_zona("(BARBOSA): PEÑA BLANCA", 1, "5000000", especial=True)]

        resultado = Balanceador().balancear(zonas, self._CARROS, None, SIN_MEJORA, {"18": {"X"}})

        assert [zona.zona.nombre for zona in resultado.zonas_sin_carro] == ["(BARBOSA): PEÑA BLANCA"]


class TestChiquinquiraSinReglaDeLado:
    """Una especial de Chiquinquirá es elegible en las cuatro rutas.

    La regla de lado dice que una zona del sur la hacen las rutas del sur, porque
    ese es su recorrido habitual. Una especial no tiene recorrido: es un cliente
    que se despacha aparte. La regla de lado es del repertorio, y las especiales
    no lo usan.
    """

    _CARROS = {
        "CHIQUINQUIRA": [
            Carro(numero="1", lado_chiquinquira=ReglaChiquinquira.SUR),
            Carro(numero="2", lado_chiquinquira=ReglaChiquinquira.SUR),
            Carro(numero="3", lado_chiquinquira=ReglaChiquinquira.NORTE),
            Carro(numero="4", lado_chiquinquira=ReglaChiquinquira.NORTE),
        ]
    }

    def _zona_con_lado(self, lado: ReglaChiquinquira, *, especial: bool) -> ZonaAgregada:
        zona = _zona("(CHIQUINQUIRA): CLIENTE GRANDE", 1, "9000000", especial=especial)
        return ZonaAgregada(
            zona=replace(zona.zona, regla_chiquinquira=lado),
            facturas=zona.facturas,
            clientes=zona.clientes,
            pesos=zona.pesos,
            kilos=zona.kilos,
        )

    def test_la_regla_dura_no_saca_a_una_especial_de_una_ruta_del_norte(self) -> None:
        """La prueba del mecanismo: la zona arranca en el 3 (norte) y su lado es
        SUR. A una zona normal la regla dura la devolvería al sur; a la especial
        la deja donde la carga la puso."""
        nombre = "(CHIQUINQUIRA): CLIENTE GRANDE"
        zonas = [self._zona_con_lado(ReglaChiquinquira.SUR, especial=True)]
        previa = {nombre: "3"}

        resultado = Balanceador().balancear(zonas, self._CARROS, previa, SIN_MEJORA, {"1": {"OTRA"}})

        assert _carro_de(resultado, nombre) == "3"

    def test_a_una_zona_normal_la_regla_dura_la_devuelve_al_sur(self) -> None:
        """La regresión: la regla sigue intacta para todo lo que no es especial."""
        nombre = "(CHIQUINQUIRA): CLIENTE GRANDE"
        zonas = [self._zona_con_lado(ReglaChiquinquira.SUR, especial=False)]
        previa = {nombre: "3"}
        # El 3 la tiene en su repertorio, así que el warm-start la pone ahí; es la
        # regla de lado, y no el repertorio, la que la saca.
        repertorio = {"1": {nombre}, "3": {nombre}}

        resultado = Balanceador().balancear(zonas, self._CARROS, previa, SIN_MEJORA, repertorio)

        assert _carro_de(resultado, nombre) == "1"

    def test_una_especial_es_elegible_en_las_cuatro_rutas(self) -> None:
        """Lo que la operación pidió: que la app sugiera el vehículo según la
        carga, entre las cuatro y no entre las dos de un lado."""
        nombre = "(CHIQUINQUIRA): CLIENTE GRANDE"
        zona = self._zona_con_lado(ReglaChiquinquira.SUR, especial=True)

        destinos = set()
        for numero in ("1", "2", "3", "4"):
            resultado = Balanceador().balancear(
                [zona], self._CARROS, {nombre: numero}, SIN_MEJORA, {"1": {"OTRA"}}
            )
            destinos.add(_carro_de(resultado, nombre))

        assert destinos == {"1", "2", "3", "4"}


class TestLaBaseEsLaUnicaFuente:
    """La marca sale de `zonas.especial`, no del nombre ni de una lista del código.

    `NOMBRES_ESPECIALES` existe solo para documentar qué se sembró en la
    migración 007. Si el balanceador o el Paso 3 la consultaran, habría dos
    verdades, y empezarían a discrepar el día que la operación marque una zona
    nueva o desmarque una de las trece: la base diría una cosa y el código otra,
    sin que nadie se enterara.
    """

    _CARROS = {"TUNJA": [Carro(numero="18"), Carro(numero="19")]}

    def test_una_zona_marcada_en_la_base_y_fuera_de_la_constante_es_especial(self) -> None:
        nombre = "(TUNJA): CLIENTE NUEVO QUE PIDE EN GRANDE"
        assert nombre not in NOMBRES_ESPECIALES

        zonas = [_zona(nombre, 1, "5000000", especial=True)]
        resultado = Balanceador().balancear(zonas, self._CARROS, None, SIN_MEJORA, {"18": {"OTRA"}})

        # Se asigna aunque no tenga repertorio: se comporta como especial.
        assert _carro_de(resultado, nombre) is not None
        assert resultado.zonas_sin_carro == []

    def test_una_zona_de_la_constante_desmarcada_en_la_base_es_normal(self) -> None:
        """La operación puede decidir que COMFABOY pasó a tener ruta fija."""
        nombre = "COMFABOY"
        assert nombre in NOMBRES_ESPECIALES

        zonas = [_zona(nombre, 1, "5000000", especial=False)]
        resultado = Balanceador().balancear(zonas, self._CARROS, None, SIN_MEJORA, {"18": {"OTRA"}})

        # Sin repertorio y sin la marca, queda sin carro como cualquier zona.
        assert [zona.zona.nombre for zona in resultado.zonas_sin_carro] == [nombre]


class TestMoverUnaEspecialAMano:
    """En el Paso 3 la especial se mueve a cualquier ruta de su municipio.

    No se le exige repertorio —no lo usa— pero sí el pool: el camión de otro
    municipio no pasa por la puerta de este cliente.
    """

    _CARROS = {
        "TUNJA": [Carro(numero="18"), Carro(numero="19")],
        "BARBOSA": [Carro(numero="5")],
    }

    def _repartir(self, especial: bool) -> ResultadoBalanceo:
        zonas = [
            _zona("(TUNJA): IMPACTA", 1, "1000000", especial=especial),
            _zona("(BARBOSA): NORMAL", 10, "2000000"),
        ]
        repertorio = {"18": {"(TUNJA): IMPACTA"}, "5": {"(BARBOSA): NORMAL"}}
        return Balanceador().balancear(zonas, self._CARROS, None, SIN_MEJORA, repertorio)

    def test_se_mueve_a_una_ruta_de_su_municipio_que_no_la_tiene_en_el_repertorio(self) -> None:
        resultado = self._repartir(especial=True)

        AjustadorDeAsignacion().mover(resultado, "(TUNJA): IMPACTA", "19")

        assert _carro_de(resultado, "(TUNJA): IMPACTA") == "19"

    def test_una_zona_normal_sigue_necesitando_el_repertorio(self) -> None:
        """La regresión: sin la marca, el 19 no la tiene permitida."""
        resultado = self._repartir(especial=False)

        with pytest.raises(MovimientoInvalido, match="no tiene permitida"):
            AjustadorDeAsignacion().mover(resultado, "(TUNJA): IMPACTA", "19")

    def test_no_se_mueve_a_una_ruta_de_otro_municipio(self) -> None:
        """Ser especial no la saca de su pool: el camión de Barbosa no llega."""
        resultado = self._repartir(especial=True)

        with pytest.raises(MovimientoInvalido, match="cliente especial de TUNJA"):
            AjustadorDeAsignacion().mover(resultado, "(TUNJA): IMPACTA", "5")
