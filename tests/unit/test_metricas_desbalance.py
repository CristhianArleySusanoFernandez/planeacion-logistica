"""Pruebas de las métricas de desbalance y de la función de costo."""

from decimal import Decimal

import pytest

from planeacion.domain.modelo import (
    UMBRAL_CV_ACEPTABLE,
    UMBRAL_CV_ATENCION,
    CargaCarro,
    Carro,
    MetricasDesbalance,
    NivelDesbalance,
    Parametros,
    ReglasBalanceo,
    UmbralesDesbalance,
    ZonaAgregada,
    clasificar_cv,
)
from planeacion.domain.modelo.parametros import (
    CLAVE_UMBRAL_CV_ACEPTABLE,
    CLAVE_UMBRAL_CV_ATENCION,
)
from planeacion.domain.servicios.balanceador import calcular_costo, calcular_metricas
from planeacion.domain.servicios.parseo_zonas import crear_zona
from planeacion.infraestructura.adaptadores.entrada.cli.balancear import (
    _TEXTO_SEMAFORO,
    _semaforo,
)
from planeacion.infraestructura.adaptadores.entrada.web.estilos import (
    _COLOR_SEMAFORO,
    color_semaforo,
)


def _carga(numero: str, clientes: int, pesos: str) -> CargaCarro:
    carga = CargaCarro(carro=Carro(numero=numero))
    carga.agregar(
        ZonaAgregada(
            zona=crear_zona(f"ZONA {numero}"),
            facturas=clientes,
            clientes=clientes,
            pesos=Decimal(pesos),
            kilos=Decimal("1"),
        )
    )
    return carga


def test_cv_y_rango_calculados_a_mano() -> None:
    # clientes [10, 20, 30]: media 20, desv. poblacional sqrt(200/3) -> cv 0.40825
    cargas = [_carga("1", 10, "10"), _carga("2", 20, "20"), _carga("3", 30, "30")]

    metricas = calcular_metricas("OTROS", cargas)

    assert metricas.municipio == "OTROS"
    assert metricas.rango_clientes == 20
    assert metricas.rango_pesos == Decimal("20")
    assert metricas.cv_clientes == pytest.approx(0.408248, abs=1e-5)
    assert metricas.cv_pesos == pytest.approx(0.408248, abs=1e-5)


def test_cargas_identicas_dan_cv_cero() -> None:
    cargas = [_carga("1", 15, "100"), _carga("2", 15, "100")]

    metricas = calcular_metricas("OTROS", cargas)

    assert metricas.cv_clientes == 0.0
    assert metricas.cv_pesos == 0.0
    assert metricas.rango_clientes == 0


def test_media_cero_no_divide_por_cero() -> None:
    cargas = [CargaCarro(carro=Carro(numero="1")), CargaCarro(carro=Carro(numero="2"))]

    metricas = calcular_metricas("OTROS", cargas)

    assert metricas.cv_clientes == 0.0
    assert metricas.cv_pesos == 0.0


def test_es_aceptable_compara_contra_el_peor_cv() -> None:
    cargas = [_carga("1", 10, "100"), _carga("2", 10, "300")]  # clientes parejos, pesos no
    metricas = calcular_metricas("OTROS", cargas)

    assert metricas.cv_clientes == 0.0
    assert metricas.cv_pesos == pytest.approx(0.5)
    assert metricas.es_aceptable(0.5)
    assert not metricas.es_aceptable(0.2)


def test_clasificar_cv_en_los_bordes_exactos() -> None:
    """Los cortes son cerrados por arriba: el corte bajo ya no es ACEPTABLE y el
    alto todavía es ATENCION."""
    assert clasificar_cv(0.0) is NivelDesbalance.ACEPTABLE
    assert clasificar_cv(UMBRAL_CV_ACEPTABLE - 0.0001) is NivelDesbalance.ACEPTABLE
    assert clasificar_cv(UMBRAL_CV_ACEPTABLE) is NivelDesbalance.ATENCION
    assert clasificar_cv(UMBRAL_CV_ATENCION) is NivelDesbalance.ATENCION
    assert clasificar_cv(UMBRAL_CV_ATENCION + 0.0001) is NivelDesbalance.CRITICO


def test_el_nivel_del_municipio_lo_marca_su_peor_dimension() -> None:
    # Clientes perfectamente parejos (CV 0) pero pesos muy dispares (CV 0,5).
    metricas = calcular_metricas("OTROS", [_carga("1", 10, "100"), _carga("2", 10, "300")])

    assert metricas.cv_clientes == 0.0
    assert metricas.nivel is NivelDesbalance.CRITICO


def test_los_adaptadores_traducen_el_mismo_nivel_del_dominio() -> None:
    """La CLI y la UI no vuelven a decidir el criterio: solo le ponen nombre y color."""
    for cv in (0.05, UMBRAL_CV_ACEPTABLE, 0.30, UMBRAL_CV_ATENCION, 0.55):
        nivel = clasificar_cv(cv)
        assert _semaforo(cv) == _TEXTO_SEMAFORO[nivel]
        assert color_semaforo(cv) == _COLOR_SEMAFORO[nivel]


def test_el_costo_pondera_con_w_clientes_y_w_pesos() -> None:
    # cv_clientes = 0 (parejos), cv_pesos = 0.5
    cargas = [_carga("1", 10, "100"), _carga("2", 10, "300")]

    solo_clientes = calcular_costo(cargas, ReglasBalanceo(w_clientes=1.0, w_pesos=0.0))
    solo_pesos = calcular_costo(cargas, ReglasBalanceo(w_clientes=0.0, w_pesos=1.0))
    mitad = calcular_costo(cargas, ReglasBalanceo(w_clientes=0.5, w_pesos=0.5))

    assert solo_clientes == pytest.approx(0.0)
    assert solo_pesos == pytest.approx(0.5)
    assert mitad == pytest.approx(0.25)


class TestKilosComoTerceraVariable:
    """Los kilos son la tercera variable del equilibrio, y el semáforo las mira."""

    def test_el_nivel_lo_marca_la_peor_de_las_tres(self) -> None:
        """Un municipio parejo en clientes y plata pero desparejo en kilos NO está
        bien repartido: alguien está cargando el doble que el resto."""
        metricas = MetricasDesbalance(
            municipio="TUNJA",
            rango_clientes=1,
            rango_pesos=Decimal("10"),
            cv_clientes=0.05,
            cv_pesos=0.05,
            cv_kilos=0.45,
        )

        assert metricas.cv_peor == 0.45
        assert metricas.nivel is NivelDesbalance.CRITICO
        assert not metricas.es_aceptable(0.40)

    def test_sin_kilos_el_nivel_no_cambia_respecto_de_antes(self) -> None:
        """`cv_kilos` nace en 0, así que una métrica vieja se sigue juzgando igual."""
        metricas = MetricasDesbalance(
            municipio="BARBOSA",
            rango_clientes=1,
            rango_pesos=Decimal("10"),
            cv_clientes=0.08,
            cv_pesos=0.09,
        )

        assert metricas.nivel is NivelDesbalance.ACEPTABLE


class TestUmbralesConfigurables:
    """Los cortes del semáforo salen de la tabla de parámetros.

    Los de julio de 2026 (0,10 y 0,20) eran de cuando la flota era otra: con las
    22 rutas actuales el reparto REAL de la operación mide 25 a 46 % de CV, así
    que los cuatro municipios salían en rojo todos los días y el color dejaba de
    informar. Un día normal daba Barbosa 4/6/20, Chiquinquirá 10/23/13, Otros
    20/18/33 y Tunja 34/35/29.
    """

    def test_los_tres_rangos_con_los_defaults_nuevos(self) -> None:
        assert clasificar_cv(0.20) is NivelDesbalance.ACEPTABLE
        assert clasificar_cv(0.30) is NivelDesbalance.ATENCION
        assert clasificar_cv(0.45) is NivelDesbalance.CRITICO

    def test_el_dia_normal_de_produccion_ya_no_es_todo_rojo(self) -> None:
        """Los CV que motivaron el cambio, con sus niveles ahora."""
        peores_por_municipio = {"BARBOSA": 0.20, "CHIQUINQUIRA": 0.23, "OTROS": 0.33, "TUNJA": 0.35}

        niveles = {m: clasificar_cv(cv) for m, cv in peores_por_municipio.items()}

        assert niveles["BARBOSA"] is NivelDesbalance.ACEPTABLE
        assert niveles["CHIQUINQUIRA"] is NivelDesbalance.ACEPTABLE
        assert niveles["OTROS"] is NivelDesbalance.ATENCION
        assert niveles["TUNJA"] is NivelDesbalance.ATENCION
        assert NivelDesbalance.CRITICO not in niveles.values()

    def test_los_tres_rangos_con_umbrales_a_medida(self) -> None:
        umbrales = UmbralesDesbalance(aceptable=0.15, atencion=0.30)

        assert clasificar_cv(0.14, umbrales) is NivelDesbalance.ACEPTABLE
        assert clasificar_cv(0.22, umbrales) is NivelDesbalance.ATENCION
        assert clasificar_cv(0.31, umbrales) is NivelDesbalance.CRITICO

    def test_los_bordes_siguen_cerrados_por_arriba_con_otros_umbrales(self) -> None:
        umbrales = UmbralesDesbalance(aceptable=0.15, atencion=0.30)

        assert clasificar_cv(0.15, umbrales) is NivelDesbalance.ATENCION
        assert clasificar_cv(0.30, umbrales) is NivelDesbalance.ATENCION

    def test_con_los_umbrales_viejos_el_dia_normal_era_todo_rojo(self) -> None:
        """La prueba del problema que se arregló, para que no vuelva sin que se note."""
        viejos = UmbralesDesbalance(aceptable=0.10, atencion=0.20)

        for cv in (0.20, 0.23, 0.33, 0.35):
            assert clasificar_cv(cv, viejos) in (
                NivelDesbalance.ATENCION,
                NivelDesbalance.CRITICO,
            )
        assert clasificar_cv(0.23, viejos) is NivelDesbalance.CRITICO

    def test_la_metrica_se_puede_juzgar_con_otros_umbrales(self) -> None:
        metricas = MetricasDesbalance(
            municipio="TUNJA",
            rango_clientes=1,
            rango_pesos=Decimal("10"),
            cv_clientes=0.34,
            cv_pesos=0.35,
            cv_kilos=0.29,
        )

        assert metricas.nivel is NivelDesbalance.ATENCION  # con los defaults nuevos
        assert metricas.nivel_segun(UmbralesDesbalance(0.10, 0.20)) is NivelDesbalance.CRITICO

    def test_los_umbrales_salen_de_los_parametros(self) -> None:
        guardados = {
            CLAVE_UMBRAL_CV_ACEPTABLE: Decimal("0.18"),
            CLAVE_UMBRAL_CV_ATENCION: Decimal("0.33"),
        }

        umbrales = Parametros(valores=guardados).umbrales_desbalance()

        assert (umbrales.aceptable, umbrales.atencion) == (0.18, 0.33)

    def test_sin_parametros_guardados_rigen_los_defaults_del_catalogo(self) -> None:
        umbrales = Parametros(valores={}).umbrales_desbalance()

        assert (umbrales.aceptable, umbrales.atencion) == (UMBRAL_CV_ACEPTABLE, UMBRAL_CV_ATENCION)

    def test_el_color_y_el_texto_siguen_al_umbral_configurado(self) -> None:
        """La leyenda y el punto tienen que usar el MISMO corte: si no, el texto
        diría 10 % mientras el color usa otro."""
        umbrales = UmbralesDesbalance(aceptable=0.15, atencion=0.30)

        assert color_semaforo(0.14, umbrales) == _COLOR_SEMAFORO[NivelDesbalance.ACEPTABLE]
        assert color_semaforo(0.14) == _COLOR_SEMAFORO[NivelDesbalance.ACEPTABLE]  # default: 0,25
        assert color_semaforo(0.20, umbrales) == _COLOR_SEMAFORO[NivelDesbalance.ATENCION]
        assert color_semaforo(0.20) == _COLOR_SEMAFORO[NivelDesbalance.ACEPTABLE]
