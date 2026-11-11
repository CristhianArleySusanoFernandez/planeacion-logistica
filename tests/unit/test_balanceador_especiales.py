"""Pruebas del Balanceador con zonas especiales.

Una **zona especial** es un cliente que pide de vez en cuando y en grande, y que
la operación despacha aparte con el vehículo que convenga ese día: COMFABOY,
IMPACTA, PIZZA NOSTRA, MEDELLIN y una decena más. No tienen carro de costumbre,
así que **no tienen repertorio**, y por eso aparecían todos los días en el aviso
de "zonas sin carro" —ruido— o, cuando pedían, quedaban sin asignar: el 27 de
octubre de 2026 COMFABOY fue la única zona que la app no pudo repartir.

Con la marca puesta y **sin casillas en Zonas por carro** son elegibles en
cualquier ruta de su pool y el balanceador las coloca por carga. Eso es la
sugerencia de vehículo que pidió la operación: no es una excepción al balanceo,
es balanceo sin repertorio. **Con casillas marcadas** la marca es una decisión
explícita: solo esas rutas, estén o no en su municipio; una sola = fija.

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

    def test_una_casilla_marcada_la_fija_aunque_esa_ruta_vaya_cargada(self) -> None:
        """La marca es una decisión explícita de la operación, no una sugerencia."""
        zonas = [
            _zona("(TUNJA): GRANDE", 100, "90000000"),
            _zona("(TUNJA): IMPACTA", 1, "1000000", especial=True),
        ]
        # Julián marcó la 18 para IMPACTA, y la 18 va cargadísima.
        repertorio = {"18": {"(TUNJA): GRANDE", "(TUNJA): IMPACTA"}}

        resultado = Balanceador().balancear(zonas, self._CARROS, None, ReglasBalanceo(), repertorio)

        assert _carro_de(resultado, "(TUNJA): IMPACTA") == "18"

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
        # Sin casillas para IMPACTA: con una marcada quedaría fija (ver abajo).
        repertorio = {"18": {"(TUNJA): OTRA"}, "5": {"(BARBOSA): NORMAL"}}
        if not especial:
            repertorio["18"].add("(TUNJA): IMPACTA")
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


class TestConRutasMarcadas:
    """Una casilla marcada en Zonas por carro es una decisión explícita.

    Julián sabe que COMFABOY se despacha con la ruta 18 y necesita poder decirlo.
    Con una ruta marcada la especial queda fija a esa ruta, esté o no en su
    municipio; con varias, el balanceador elige por carga entre ellas; sin
    ninguna, sigue como siempre: cualquier ruta de su municipio.
    """

    _CARROS = {
        "BARBOSA": [Carro(numero="5"), Carro(numero="7")],
        "TUNJA": [Carro(numero="18"), Carro(numero="19"), Carro(numero="20")],
    }

    def test_una_marcada_fuera_de_su_municipio_va_solo_a_esa(self) -> None:
        """COMFABOY es de BARBOSA en la base y Julián la marcó en la 18 de TUNJA."""
        zonas = [
            _zona("(BARBOSA): COMFABOY", 1, "5000000", especial=True),
            _zona("(TUNJA): GRANDE", 100, "90000000"),
        ]
        repertorio = {"18": {"(BARBOSA): COMFABOY", "(TUNJA): GRANDE"}}

        resultado = Balanceador().balancear(zonas, self._CARROS, None, ReglasBalanceo(), repertorio)

        assert _carro_de(resultado, "(BARBOSA): COMFABOY") == "18"
        assert resultado.zonas_sin_carro == []

    def test_con_dos_marcadas_elige_por_carga_entre_las_dos(self) -> None:
        zonas = [
            _zona("(TUNJA): GRANDE", 100, "90000000"),
            _zona("(TUNJA): MEDIANA", 50, "40000000"),
            _zona("(TUNJA): IMPACTA", 1, "1000000", especial=True),
        ]
        # Marcada en 18 y 19; el 20 va vacío pero NO está marcado.
        repertorio = {
            "18": {"(TUNJA): GRANDE", "(TUNJA): IMPACTA"},
            "19": {"(TUNJA): MEDIANA", "(TUNJA): IMPACTA"},
        }

        resultado = Balanceador().balancear(zonas, self._CARROS, None, SIN_MEJORA, repertorio)

        assert _carro_de(resultado, "(TUNJA): IMPACTA") == "19"

    def test_sin_marcas_sigue_yendo_a_cualquier_ruta_de_su_municipio(self) -> None:
        zonas = [
            _zona("(TUNJA): GRANDE", 100, "90000000"),
            _zona("(TUNJA): IMPACTA", 1, "1000000", especial=True),
        ]
        repertorio = {"18": {"(TUNJA): GRANDE"}}

        resultado = Balanceador().balancear(zonas, self._CARROS, None, SIN_MEJORA, repertorio)

        assert _carro_de(resultado, "(TUNJA): IMPACTA") in {"19", "20"}

    def test_una_zona_normal_con_una_marca_no_cambia(self) -> None:
        """La regresión: para una normal una marca ya era su repertorio."""
        zonas = [_zona("(TUNJA): NORMAL", 10, "5000000")]
        repertorio = {"19": {"(TUNJA): NORMAL"}}

        resultado = Balanceador().balancear(zonas, self._CARROS, None, SIN_MEJORA, repertorio)

        assert _carro_de(resultado, "(TUNJA): NORMAL") == "19"

    def test_una_marca_en_una_ruta_que_hoy_no_esta_activa_no_la_deja_sin_carro(self) -> None:
        """La 23 está inactiva: la marca no puede cumplirse y la especial vuelve a su pool."""
        zonas = [_zona("(TUNJA): IMPACTA", 1, "1000000", especial=True)]
        repertorio = {"23": {"(TUNJA): IMPACTA"}}

        resultado = Balanceador().balancear(zonas, self._CARROS, None, SIN_MEJORA, repertorio)

        assert _carro_de(resultado, "(TUNJA): IMPACTA") in {"18", "19", "20"}

    def test_en_chiquinquira_la_marca_en_una_ruta_del_otro_lado_se_respeta(self) -> None:
        """La regla de lado no le aplica a una especial, con marca tampoco."""
        carros = {
            "CHIQUINQUIRA": [
                Carro(numero="1", lado_chiquinquira=ReglaChiquinquira.SUR),
                Carro(numero="2", lado_chiquinquira=ReglaChiquinquira.SUR),
                Carro(numero="3", lado_chiquinquira=ReglaChiquinquira.NORTE),
            ]
        }
        especial = _zona("(CHIQUINQUIRA): PIZZA NOSTRA RUTA SUR 1", 1, "1000000", especial=True)
        assert especial.zona.regla_chiquinquira is ReglaChiquinquira.SUR
        repertorio = {"3": {especial.zona.nombre}}

        resultado = Balanceador().balancear([especial], carros, None, ReglasBalanceo(), repertorio)

        assert _carro_de(resultado, especial.zona.nombre) == "3"


class TestMoverUnaEspecialConMarcas:
    _CARROS = {
        "BARBOSA": [Carro(numero="5"), Carro(numero="7")],
        "TUNJA": [Carro(numero="18"), Carro(numero="19"), Carro(numero="20")],
    }

    def _repartir(self, repertorio: dict[str, set[str]]) -> ResultadoBalanceo:
        zonas = [
            _zona("(BARBOSA): COMFABOY", 1, "5000000", especial=True),
            _zona("(BARBOSA): NORMAL", 10, "2000000"),
            _zona("(TUNJA): GRANDE", 100, "90000000"),
        ]
        repertorio = {**repertorio, "5": {"(BARBOSA): NORMAL"}, "20": {"(TUNJA): GRANDE"}}
        return Balanceador().balancear(zonas, self._CARROS, None, SIN_MEJORA, repertorio)

    def test_con_una_sola_marca_no_se_mueve_a_ninguna_parte(self) -> None:
        resultado = self._repartir({"18": {"(BARBOSA): COMFABOY"}})

        with pytest.raises(MovimientoInvalido, match=r"ruta\(s\) marcada\(s\) \(18\)"):
            AjustadorDeAsignacion().mover(resultado, "(BARBOSA): COMFABOY", "19")
        with pytest.raises(MovimientoInvalido, match="marcada"):
            AjustadorDeAsignacion().mover(resultado, "(BARBOSA): COMFABOY", "7")
        assert resultado.rutas_marcadas("(BARBOSA): COMFABOY") == {"18"}

    def test_con_dos_marcas_se_mueve_entre_ellas_y_a_ninguna_otra(self) -> None:
        resultado = self._repartir({"18": {"(BARBOSA): COMFABOY"}, "19": {"(BARBOSA): COMFABOY"}})
        origen = _carro_de(resultado, "(BARBOSA): COMFABOY")
        destino = "19" if origen == "18" else "18"

        AjustadorDeAsignacion().mover(resultado, "(BARBOSA): COMFABOY", destino)
        assert _carro_de(resultado, "(BARBOSA): COMFABOY") == destino

        with pytest.raises(MovimientoInvalido, match="18, 19"):
            AjustadorDeAsignacion().mover(resultado, "(BARBOSA): COMFABOY", "20")

    def test_sin_marcas_sigue_la_regla_del_municipio(self) -> None:
        resultado = self._repartir({})

        with pytest.raises(MovimientoInvalido, match="cliente especial de BARBOSA"):
            AjustadorDeAsignacion().mover(resultado, "(BARBOSA): COMFABOY", "18")
