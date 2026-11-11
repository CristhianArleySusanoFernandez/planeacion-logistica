"""Pruebas de las alertas operativas: pocos clientes, muchas facturas y promedio Vh.

Las tres son metas y no reglas, así que lo que se prueba es que **avisen bien**:
el borde exacto del umbral, a quién le aplican y que no inventen alertas en un
día normal. Que no cambien el reparto se prueba por construcción: estas
funciones reciben cargas ya repartidas y solo devuelven texto.
"""

from decimal import Decimal

from planeacion.domain.modelo import CargaCarro, Carro, Municipio, Zona, ZonaAgregada
from planeacion.domain.servicios.alertas_operativas import (
    PromedioPorVehiculo,
    TipoAlerta,
    alerta_de_promedio_por_vehiculo,
    alertas_de_conductores,
    alertas_por_ruta,
    divisor_de_vehiculos,
    nota_de_clientes_especiales,
    promedio_por_vehiculo,
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


# La flota de prueba: cinco rutas, cuatro activas, tres camiones (Fabián lleva dos planillas).
_FLOTA = [
    Carro(numero="1", conductor="FABIAN 1", conductor_clave="FABIAN"),
    Carro(numero="2", conductor="FABIAN 2", conductor_clave="FABIAN"),
    Carro(numero="18", conductor="JOSE YOVANY"),  # sin clave: se deduce del nombre
    Carro(numero="19", conductor="LUIS"),
    Carro(numero="23", conductor="KEVIN", activo=False),
]


def _promedio(total_facturas: int, vehiculos_referencia: int = 12) -> PromedioPorVehiculo:
    return promedio_por_vehiculo(total_facturas, _FLOTA, vehiculos_referencia)


class TestDivisorDeVehiculos:
    def test_automatico_cuenta_camiones_no_rutas(self) -> None:
        """Cero = automático: tres camiones (Fabián una vez), la 23 inactiva no cuenta."""
        assert divisor_de_vehiculos(_FLOTA, 0) == 3

    def test_la_anulacion_manual_se_usa_tal_cual(self) -> None:
        assert divisor_de_vehiculos(_FLOTA, 12) == 12
        assert divisor_de_vehiculos(_FLOTA, 22) == 22

    def test_sin_flota_el_automatico_es_cero_y_no_divide(self) -> None:
        promedio = promedio_por_vehiculo(1303, [], 0)

        assert promedio.divisor == 0
        assert alerta_de_promedio_por_vehiculo(promedio) is None

    def test_el_texto_muestra_el_divisor_usado(self) -> None:
        """«1.302 facturas / 12 vehículos = 108,5», para que nadie adivine de dónde sale."""
        assert _promedio(1302).texto == "1.302 facturas / 12 vehículos = 108,5"
        assert _promedio(1302, 0).texto == "1.302 facturas / 3 camiones activos = 434,0"


class TestPromedioPorVehiculo:
    def test_sobre_el_umbral_sugiere_revisar_el_externo(self) -> None:
        alerta = alerta_de_promedio_por_vehiculo(_promedio(1400))

        assert alerta is not None
        assert alerta.valor == 116  # 1400 / 12
        assert "revisar si hace falta carro externo" in alerta.texto
        assert "1.400 facturas / 12 vehículos" in alerta.texto
        assert alerta.conductor is None

    def test_justo_en_el_umbral_no_avisa(self) -> None:
        """110 × 12 = 1.320 facturas: el promedio da exactamente el umbral."""
        assert alerta_de_promedio_por_vehiculo(_promedio(1320)) is None

    def test_por_debajo_no_avisa(self) -> None:
        assert alerta_de_promedio_por_vehiculo(_promedio(1303)) is None

    def test_el_divisor_manual_se_respeta(self) -> None:
        assert alerta_de_promedio_por_vehiculo(_promedio(1303, 22)) is None
        alerta = alerta_de_promedio_por_vehiculo(_promedio(1303, 10))
        assert alerta is not None and alerta.valor == 130

    def test_con_el_divisor_automatico_el_umbral_de_110_no_se_recalibra_solo(self) -> None:
        """El acoplamiento documentado: con 12 el día de 1.303 facturas no avisa (108);
        con 17 camiones daría 76 y tampoco. Cambiar el divisor sin tocar el umbral
        apaga la alerta de carro externo en silencio: por eso el default sigue en 12."""
        diecisiete = [Carro(numero=str(n), conductor=f"C{n}") for n in range(17)]
        con_doce = promedio_por_vehiculo(1400, diecisiete, 12)
        automatico = promedio_por_vehiculo(1400, diecisiete, 0)

        assert alerta_de_promedio_por_vehiculo(con_doce) is not None  # 116 > 110
        assert automatico.divisor == 17 and alerta_de_promedio_por_vehiculo(automatico) is None  # 82


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
        del_dia = alerta_de_promedio_por_vehiculo(_promedio(1400))
        assert del_dia is not None

        assert alertas_por_ruta([del_dia], cargas) == {}


class TestNotaDeClientesEspeciales:
    """El aviso de composición de la columna Alerta de BASE.

    No es una alerta de umbral: la app eligió el vehículo por la carga del día y
    no por costumbre —un cliente especial no tiene carro habitual—, así que quien
    despacha tiene que confirmar que ese camión le sirve: horario de recepción,
    tamaño, acceso.
    """

    def _con_zonas(self, *zonas: ZonaAgregada) -> CargaCarro:
        return CargaCarro(carro=Carro(numero="18", conductor="JOSE"), zonas=list(zonas))

    def _zona(self, nombre: str, *, especial: bool) -> ZonaAgregada:
        return ZonaAgregada(
            zona=Zona(nombre=nombre, municipio=Municipio(nombre="TUNJA"), especial=especial),
            facturas=1,
            clientes=1,
            pesos=Decimal("1000"),
            kilos=Decimal("10"),
        )

    def test_nombra_al_cliente_y_pide_verificar(self) -> None:
        carga = self._con_zonas(self._zona("COMFABOY", especial=True))

        nota = nota_de_clientes_especiales(carga)

        assert nota is not None
        assert "COMFABOY" in nota
        assert "verifique el vehículo" in nota

    def test_una_ruta_sin_especiales_no_dice_nada(self) -> None:
        """La columna queda vacía en un día normal."""
        carga = self._con_zonas(self._zona("(TUNJA): NIEVES", especial=False))

        assert nota_de_clientes_especiales(carga) is None

    def test_varios_especiales_en_la_misma_ruta_van_juntos_y_ordenados(self) -> None:
        carga = self._con_zonas(
            self._zona("IMPACTA", especial=True),
            self._zona("(TUNJA): NIEVES", especial=False),
            self._zona("COMFABOY", especial=True),
        )

        nota = nota_de_clientes_especiales(carga)

        assert nota == "Cliente especial (COMFABOY, IMPACTA): verifique el vehículo"
