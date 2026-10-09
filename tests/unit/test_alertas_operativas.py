"""Pruebas de las alertas operativas: pocos clientes, muchas facturas y promedio Vh.

Las tres son metas y no reglas, así que lo que se prueba es que **avisen bien**:
el borde exacto del umbral, a quién le aplican y que no inventen alertas en un
día normal. Que no cambien el reparto se prueba por construcción: estas
funciones reciben cargas ya repartidas y solo devuelven texto.
"""

from decimal import Decimal

from planeacion.domain.modelo import CargaCarro, Carro, Municipio, Zona, ZonaAgregada
from planeacion.domain.servicios.alertas_operativas import (
    TipoAlerta,
    alerta_de_promedio_por_vehiculo,
    alertas_de_conductores,
    alertas_por_ruta,
)


def _carga(
    numero: str,
    conductor: str,
    clientes: int,
    facturas: int | None = None,
    municipio: str = "TUNJA",
) -> CargaCarro:
    pool = Municipio(nombre=municipio)
    zona = ZonaAgregada(
        zona=Zona(nombre=f"({municipio}): ZONA {numero}", municipio=pool),
        facturas=facturas if facturas is not None else clientes,
        clientes=clientes,
        pesos=Decimal("1000"),
        kilos=Decimal("10"),
    )
    carro = Carro(
        numero=numero,
        conductor=conductor,
        conductor_clave=conductor.rsplit(" ", 1)[0] if conductor[-1].isdigit() else conductor,
        municipio=pool,
    )
    return CargaCarro(carro=carro, zonas=[zona])


class TestMinimoDeClientes:
    def test_por_debajo_del_minimo_avisa_con_el_numero(self) -> None:
        alertas = alertas_de_conductores({"TUNJA": [_carga("19", "WILMAR", clientes=42)]})

        assert len(alertas) == 1
        assert alertas[0].tipo is TipoAlerta.POCOS_CLIENTES
        assert alertas[0].valor == 42
        assert "42 clientes" in alertas[0].texto
        assert alertas[0].conductor == "WILMAR"

    def test_justo_en_el_umbral_no_avisa(self) -> None:
        """50 clientes cumplen la meta: el aviso es para quien queda POR DEBAJO."""
        assert alertas_de_conductores({"TUNJA": [_carga("19", "WILMAR", clientes=50)]}) == []

    def test_por_encima_no_avisa(self) -> None:
        assert alertas_de_conductores({"TUNJA": [_carga("19", "WILMAR", clientes=51)]}) == []

    def test_las_dos_rutas_de_un_conductor_suman_antes_de_comparar(self) -> None:
        """Dos rutas de 30 clientes no son dos problemas: es un conductor con 60."""
        cargas = [
            _carga("14", "JAIRO GARZON 1", clientes=30),
            _carga("15", "JAIRO GARZON 2", clientes=30),
        ]

        assert alertas_de_conductores({"TUNJA": cargas}) == []

    def test_las_viajeras_quedan_fuera_de_la_meta_de_clientes(self) -> None:
        """Pocas visitas y mucho kilómetro es su naturaleza, no un problema."""
        cargas = [_carga("11", "GILBERTO", clientes=26, municipio="OTROS")]

        assert alertas_de_conductores({"OTROS": cargas}) == []

    def test_el_minimo_es_parametrizable(self) -> None:
        cargas = {"TUNJA": [_carga("19", "WILMAR", clientes=42)]}

        assert alertas_de_conductores(cargas, min_clientes=40) == []


class TestMaximoDeFacturas:
    def test_por_encima_del_maximo_avisa(self) -> None:
        cargas = {"CHIQUINQUIRA": [_carga("1", "FABIAN 1", clientes=90, facturas=111)]}

        alertas = alertas_de_conductores(cargas)

        assert [a.tipo for a in alertas] == [TipoAlerta.MUCHAS_FACTURAS]
        assert alertas[0].valor == 111

    def test_justo_en_el_umbral_no_avisa(self) -> None:
        cargas = {"CHIQUINQUIRA": [_carga("1", "FABIAN 1", clientes=90, facturas=110)]}

        assert alertas_de_conductores(cargas) == []

    def test_aplica_tambien_a_las_viajeras(self) -> None:
        """A diferencia del mínimo de clientes, el exceso de facturas es carga de
        trabajo y le importa a cualquier ruta."""
        cargas = {"OTROS": [_carga("8", "CAMILO SOTELO", clientes=45, facturas=130, municipio="OTROS")]}

        assert [a.tipo for a in alertas_de_conductores(cargas)] == [TipoAlerta.MUCHAS_FACTURAS]


class TestPromedioPorVehiculo:
    def test_sobre_el_umbral_sugiere_revisar_el_externo(self) -> None:
        alerta = alerta_de_promedio_por_vehiculo(total_facturas=1400)

        assert alerta is not None
        assert alerta.valor == 116  # 1400 / 12
        assert "revisar si hace falta carro externo" in alerta.texto
        assert alerta.conductor is None

    def test_justo_en_el_umbral_no_avisa(self) -> None:
        """110 × 12 = 1.320 facturas: el promedio da exactamente el umbral."""
        assert alerta_de_promedio_por_vehiculo(total_facturas=1320) is None

    def test_por_debajo_no_avisa(self) -> None:
        assert alerta_de_promedio_por_vehiculo(total_facturas=1303) is None

    def test_el_divisor_es_fijo_y_parametrizable(self) -> None:
        """Es el divisor de la hoja de Julián, no la cantidad de carros con carga:
        cambiarlo daría otro número y rompería la comparación con lo que ya miran."""
        assert alerta_de_promedio_por_vehiculo(1303, vehiculos_referencia=22) is None
        alerta = alerta_de_promedio_por_vehiculo(1303, vehiculos_referencia=10)
        assert alerta is not None and alerta.valor == 130

    def test_un_divisor_invalido_no_hace_fallar_la_pantalla(self) -> None:
        assert alerta_de_promedio_por_vehiculo(1303, vehiculos_referencia=0) is None


class TestAlertasPorRuta:
    def test_las_dos_rutas_del_conductor_heredan_su_alerta(self) -> None:
        cargas = [
            _carga("14", "JAIRO GARZON 1", clientes=20),
            _carga("15", "JAIRO GARZON 2", clientes=20),
        ]
        alertas = alertas_de_conductores({"TUNJA": cargas})

        por_ruta = alertas_por_ruta(alertas, cargas)

        assert por_ruta == {"14": "pocos clientes: 40", "15": "pocos clientes: 40"}

    def test_un_dia_sin_alertas_no_escribe_nada(self) -> None:
        cargas = [_carga("19", "WILMAR", clientes=80)]

        assert alertas_por_ruta(alertas_de_conductores({"TUNJA": cargas}), cargas) == {}

    def test_la_alerta_del_dia_no_cuelga_de_ninguna_ruta(self) -> None:
        """El promedio por vehículo es del día entero: no tiene conductor."""
        cargas = [_carga("19", "WILMAR", clientes=80)]
        del_dia = alerta_de_promedio_por_vehiculo(total_facturas=1400)
        assert del_dia is not None

        assert alertas_por_ruta([del_dia], cargas) == {}
