"""Pruebas de la alerta de planillas desparejas.

Cinco conductores llevan dos planillas del mismo camión y la operación partió
zonas en dos justamente para que las dos lleguen parejas a bodega. El
balanceador reparte por ruta y no sabe que dos rutas comparten camión: puede
dejar una planilla con 310 kg y la otra con 160 sin que ninguna métrica se
entere —por municipio el CV no lo ve, por conductor la suma lo esconde.

Lo que se prueba es que **avise bien**: el borde exacto del umbral en pesos y en
kilos, que basta con que una se pase, que los clientes NO se comparan (Julián
reparte las mitades por carga, no por paradas), que nombra las planillas por
número de ruta, y que no inventa alertas donde no hay dos planillas. Que no
cambie el reparto se prueba por construcción: recibe cargas ya repartidas y solo
devuelve texto.
"""

from decimal import Decimal

from planeacion.domain.modelo import CargaCarro, Carro, Municipio, Zona, ZonaAgregada
from planeacion.domain.servicios.alertas_operativas import (
    TipoAlerta,
    alertas_de_planillas,
    alertas_por_ruta,
)

_UMBRAL = Decimal("0.75")


def _planilla(
    numero: str,
    conductor_clave: str,
    *,
    clientes: int = 50,
    pesos: str = "1000000",
    kilos: str = "200",
    conductor: str | None = None,
) -> CargaCarro:
    pool = Municipio(nombre="TUNJA")
    zona = ZonaAgregada(
        zona=Zona(nombre=f"(TUNJA): ZONA {numero}", municipio=pool),
        facturas=clientes,
        clientes=clientes,
        pesos=Decimal(pesos),
        kilos=Decimal(kilos),
    )
    carro = Carro(
        numero=numero,
        conductor=conductor or conductor_clave,
        conductor_clave=conductor_clave,
        municipio=pool,
    )
    return CargaCarro(carro=carro, zonas=[zona])


def _alertas(*cargas: CargaCarro, umbral: Decimal = _UMBRAL) -> list:
    return alertas_de_planillas({"TUNJA": list(cargas)}, umbral)


class TestLosTresRangosEnKilos:
    """El caso del enunciado: 310 kg contra 160 kg es un 94 % de más."""

    def test_por_debajo_del_umbral_no_avisa(self) -> None:
        # 170 contra 100 = 70 %, menos del 75 %.
        assert _alertas(_planilla("1", "FABIAN", kilos="170"), _planilla("2", "FABIAN", kilos="100")) == []

    def test_exactamente_en_el_umbral_no_avisa(self) -> None:
        """Tiene que SUPERAR el umbral: 175 contra 100 es justo el 75 %."""
        assert _alertas(_planilla("1", "FABIAN", kilos="175"), _planilla("2", "FABIAN", kilos="100")) == []

    def test_por_encima_del_umbral_avisa_nombrando_las_rutas(self) -> None:
        alertas = _alertas(_planilla("1", "FABIAN", kilos="310"), _planilla("2", "FABIAN", kilos="160"))

        assert len(alertas) == 1
        alerta = alertas[0]
        assert alerta.tipo is TipoAlerta.PLANILLAS_DESPAREJAS
        assert alerta.conductor == "FABIAN"
        assert "Planillas de FABIAN desparejas" in alerta.texto
        assert "la ruta 1 lleva 310 kg y la 2 lleva 160 kg" in alerta.texto
        assert alerta.valor == 93  # (310 - 160) / 160 = 93,75 %, truncado
        assert alerta.umbral == 75

    def test_un_kilo_por_encima_del_umbral_ya_avisa(self) -> None:
        alertas = _alertas(_planilla("1", "FABIAN", kilos="176"), _planilla("2", "FABIAN", kilos="100"))

        assert len(alertas) == 1


class TestPesosYClientes:
    def test_en_pesos(self) -> None:
        alertas = _alertas(
            _planilla("1", "FABIAN", pesos="4000000"), _planilla("2", "FABIAN", pesos="2000000")
        )

        assert len(alertas) == 1
        assert "en pesos la ruta 1 lleva $4,000,000 y la 2 lleva $2,000,000" in alertas[0].texto

    def test_en_pesos_justo_en_el_umbral_no_avisa(self) -> None:
        # 3.500.000 contra 2.000.000 = 75 % exacto.
        assert (
            _alertas(_planilla("1", "FABIAN", pesos="3500000"), _planilla("2", "FABIAN", pesos="2000000"))
            == []
        )

    def test_los_clientes_no_se_comparan(self) -> None:
        """En los 7 días medidos Julián deja planillas con 190 % más clientes que su
        pareja y los pesos parejos: reparte por carga, no por paradas. Un camión con
        el triple de clientes en una planilla no es un desparejo."""
        assert _alertas(_planilla("1", "FABIAN", clientes=90), _planilla("2", "FABIAN", clientes=30)) == []

    def test_una_planilla_sin_clientes_tampoco_avisa_por_clientes(self) -> None:
        assert _alertas(_planilla("1", "FABIAN", clientes=40), _planilla("2", "FABIAN", clientes=0)) == []

    def test_basta_con_que_una_variable_se_pase(self) -> None:
        """Clientes y pesos parejos, kilos no: avisa igual, y dice por cuál."""
        alertas = _alertas(_planilla("1", "FABIAN", kilos="400"), _planilla("2", "FABIAN", kilos="200"))

        assert len(alertas) == 1
        assert "en kilos" in alertas[0].texto
        assert "en clientes" not in alertas[0].texto
        assert "en pesos" not in alertas[0].texto

    def test_si_se_pasan_varias_las_lista_todas_en_una_sola_alerta(self) -> None:
        """Un camión desparejo es UN problema, no dos. Y los clientes, aunque también
        estén desparejos, no aparecen en el texto."""
        alertas = _alertas(
            _planilla("1", "FABIAN", clientes=80, pesos="4000000", kilos="400"),
            _planilla("2", "FABIAN", clientes=40, pesos="2000000", kilos="200"),
        )

        assert len(alertas) == 1
        texto = alertas[0].texto
        assert "en pesos" in texto and "en kilos" in texto
        assert "en clientes" not in texto


class TestQuienesTienenPlanillas:
    def test_un_conductor_de_una_sola_ruta_no_tiene_planillas_que_comparar(self) -> None:
        assert _alertas(_planilla("18", "JOSE YOVANY", kilos="900")) == []

    def test_dos_conductores_distintos_no_se_comparan_entre_si(self) -> None:
        """Que el 18 lleve el triple que el 19 es desbalance del pool, no planillas."""
        a, b = _planilla("18", "JOSE YOVANY", kilos="900"), _planilla("19", "LUIS", kilos="300")

        assert _alertas(a, b) == []

    def test_javier_reyes_se_nombra_por_ruta_porque_no_tiene_sufijo(self) -> None:
        """Las rutas 14 y 15 son las dos `JAVIER REYES`, sin ningún 1 ni 2."""
        alertas = _alertas(
            _planilla("14", "JAVIER REYES", kilos="310"), _planilla("15", "JAVIER REYES", kilos="160")
        )

        assert len(alertas) == 1
        assert "(rutas 14, 15)" in alertas[0].texto
        assert "la ruta 14 lleva 310 kg y la 15 lleva 160 kg" in alertas[0].texto

    def test_funciona_con_el_sufijo_derivado_del_nombre(self) -> None:
        """Base sin `conductor_clave`: la clave sale del nombre `FABIAN 1`/`FABIAN 2`."""
        zonas_a = _planilla("1", "x", kilos="310").zonas
        zonas_b = _planilla("2", "x", kilos="160").zonas
        a = CargaCarro(carro=Carro(numero="1", conductor="FABIAN 1"), zonas=zonas_a)
        b = CargaCarro(carro=Carro(numero="2", conductor="FABIAN 2"), zonas=zonas_b)

        alertas = alertas_de_planillas({"CHIQUINQUIRA": [a, b]})

        assert len(alertas) == 1 and alertas[0].conductor == "FABIAN"

    def test_cada_conductor_con_planillas_desparejas_tiene_su_alerta(self) -> None:
        alertas = _alertas(
            _planilla("1", "FABIAN", kilos="310"),
            _planilla("2", "FABIAN", kilos="160"),
            _planilla("16", "CARLOS", kilos="200"),
            _planilla("17", "CARLOS", kilos="210"),
            _planilla("14", "JAVIER REYES", kilos="500"),
            _planilla("15", "JAVIER REYES", kilos="100"),
        )

        assert sorted(a.conductor for a in alertas) == ["FABIAN", "JAVIER REYES"]


class TestCasosBorde:
    def test_una_planilla_vacia_frente_a_otra_cargada_siempre_avisa(self) -> None:
        """Dividir por cero no es excusa: una planilla en cero es el peor desparejo."""
        alertas = _alertas(_planilla("1", "FABIAN", kilos="310"), _planilla("2", "FABIAN", kilos="0"))

        assert len(alertas) == 1
        assert "en kilos la ruta 1 lleva 310 kg y la 2 lleva 0 kg" in alertas[0].texto
        assert alertas[0].valor == 999

    def test_las_dos_vacias_en_una_variable_no_avisan_por_esa_variable(self) -> None:
        assert _alertas(_planilla("1", "FABIAN", kilos="0"), _planilla("2", "FABIAN", kilos="0")) == []

    def test_el_umbral_es_un_parametro(self) -> None:
        """Con 1,00 el 310 contra 160 (94 %) ya no avisa; con el default sí, y un
        umbral más exigente (0,35) atrapa hasta el 150 contra 100."""
        muy_desparejas = (_planilla("1", "F", kilos="310"), _planilla("2", "F", kilos="160"))
        algo_desparejas = (_planilla("1", "F", kilos="150"), _planilla("2", "F", kilos="100"))

        assert _alertas(*muy_desparejas, umbral=Decimal("1.00")) == []
        assert len(_alertas(*muy_desparejas)) == 1
        assert _alertas(*algo_desparejas) == []
        assert len(_alertas(*algo_desparejas, umbral=Decimal("0.35"))) == 1

    def test_el_reparto_no_se_toca(self) -> None:
        """Por construcción: la función recibe las cargas y devuelve texto."""
        a, b = _planilla("1", "FABIAN", kilos="310"), _planilla("2", "FABIAN", kilos="160")
        antes = ([z.zona.nombre for z in a.zonas], [z.zona.nombre for z in b.zonas])

        _alertas(a, b)

        assert ([z.zona.nombre for z in a.zonas], [z.zona.nombre for z in b.zonas]) == antes


class TestEnLaColumnaAlertaDeBase:
    def test_la_alerta_llega_a_las_dos_rutas_del_conductor(self) -> None:
        """La columna Alerta de BASE es por ruta: las dos planillas la muestran."""
        a, b = _planilla("1", "FABIAN", kilos="310"), _planilla("2", "FABIAN", kilos="160")
        alertas = _alertas(a, b)

        por_ruta = alertas_por_ruta(alertas, [a, b])

        assert set(por_ruta) == {"1", "2"}
        assert por_ruta["1"] == por_ruta["2"] == "planillas desparejas: 93"

    def test_una_ruta_de_otro_conductor_no_la_hereda(self) -> None:
        a, b, c = (
            _planilla("1", "FABIAN", kilos="310"),
            _planilla("2", "FABIAN", kilos="160"),
            _planilla("18", "JOSE YOVANY"),
        )

        por_ruta = alertas_por_ruta(_alertas(a, b, c), [a, b, c])

        assert "18" not in por_ruta
