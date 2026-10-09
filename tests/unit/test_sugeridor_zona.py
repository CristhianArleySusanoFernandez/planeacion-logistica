"""Pruebas del SugeridorDeZona: voto mayoritario por (ciudad, barrio) con fallback a ciudad."""

from planeacion.domain.modelo import Cliente, ConfianzaSugerencia, Zona
from planeacion.domain.servicios.parseo_zonas import crear_zona
from planeacion.domain.servicios.sugeridor_zona import SugeridorDeZona

ZONA_CENTRO = crear_zona("(TUNJA):  RUTA CENTRO 1")
ZONA_NIEVES = crear_zona("(TUNJA):  NIEVES")
ZONA_OCCIDENTE = crear_zona("(TUNJA):  RUTA OCCIDENTE")


def _cliente(codigo: str, ciudad: str, barrio: str, zona: Zona) -> Cliente:
    return Cliente(codigo=codigo, ciudad=ciudad, barrio=barrio, zona=zona)


VECINDARIO = [
    _cliente("1", "TUNJA", "CENTRO", ZONA_CENTRO),
    _cliente("2", "TUNJA", "CENTRO", ZONA_CENTRO),
    _cliente("3", "TUNJA", "CENTRO", ZONA_CENTRO),
    _cliente("4", "TUNJA", "CENTRO", ZONA_NIEVES),
    _cliente("5", "TUNJA", "LAS NIEVES", ZONA_NIEVES),
    _cliente("6", "TUNJA", "LAS NIEVES", ZONA_NIEVES),
    _cliente("7", "TUNJA", "MALDONADO", ZONA_CENTRO),
]


def test_gana_la_zona_mayoritaria_del_barrio_y_las_demas_quedan_a_la_vista() -> None:
    sugerencia = SugeridorDeZona(VECINDARIO).sugerir("TUNJA", "CENTRO")

    assert sugerencia is not None
    assert sugerencia.zona_sugerida == ZONA_CENTRO
    assert sugerencia.vecinos_en_zona == 3
    assert sugerencia.total_vecinos == 4
    assert sugerencia.confianza == ConfianzaSugerencia.BARRIO
    # Las dos opciones con su respaldo: el margen es parte de la decisión.
    assert [(o.zona, o.vecinos) for o in sugerencia.opciones] == [(ZONA_CENTRO, 3), (ZONA_NIEVES, 1)]
    assert [round(o.porcentaje, 2) for o in sugerencia.opciones] == [0.75, 0.25]


def test_la_normalizacion_casa_el_formato_del_ecom_con_la_maestra() -> None:
    # ECOM: "15001 - TUNJA" con acentos y espacios; maestra: "TUNJA".
    sugerencia = SugeridorDeZona(VECINDARIO).sugerir("15001 - tunjá", "  centro ")

    assert sugerencia is not None
    assert sugerencia.zona_sugerida == ZONA_CENTRO
    assert sugerencia.confianza == ConfianzaSugerencia.BARRIO


def test_sin_vecinos_del_barrio_cae_a_ciudad_con_confianza_menor() -> None:
    sugerencia = SugeridorDeZona(VECINDARIO).sugerir("TUNJA", "BARRIO NUEVO")

    assert sugerencia is not None
    assert sugerencia.confianza == ConfianzaSugerencia.CIUDAD
    assert sugerencia.total_vecinos == 7  # toda la ciudad vota
    assert sugerencia.zona_sugerida == ZONA_CENTRO  # 4 votos contra 3 de NIEVES


def test_sin_ninguna_coincidencia_devuelve_none() -> None:
    assert SugeridorDeZona(VECINDARIO).sugerir("VILLAVICENCIO", "CENTRO") is None
    assert SugeridorDeZona([]).sugerir("TUNJA", "CENTRO") is None


def test_empate_se_resuelve_por_nombre_de_zona_deterministicamente() -> None:
    empatados = [
        _cliente("1", "TUNJA", "CENTRO", ZONA_CENTRO),
        _cliente("2", "TUNJA", "CENTRO", ZONA_NIEVES),
    ]
    sugerencia = SugeridorDeZona(empatados).sugerir("TUNJA", "CENTRO")

    assert sugerencia is not None
    # 1 voto cada una: gana "(TUNJA): NIEVES" sobre "(TUNJA): RUTA CENTRO 1" (N < R).
    assert sugerencia.zona_sugerida == ZONA_NIEVES
    assert sugerencia.vecinos_en_zona == 1


def test_ignora_clientes_sin_zona_en_el_vecindario() -> None:
    vecinos = [
        _cliente("1", "TUNJA", "CENTRO", ZONA_CENTRO),
        Cliente(codigo="2", ciudad="TUNJA", barrio="CENTRO", zona=None),
    ]
    sugerencia = SugeridorDeZona(vecinos).sugerir("TUNJA", "CENTRO")

    assert sugerencia is not None
    assert sugerencia.total_vecinos == 1


def test_respeta_el_maximo_de_opciones() -> None:
    vecinos = VECINDARIO + [
        _cliente("7", "TUNJA", "CENTRO", ZONA_OCCIDENTE),
    ]
    sugerencia = SugeridorDeZona(vecinos).sugerir("TUNJA", "CENTRO", max_opciones=2)

    assert sugerencia is not None
    assert len(sugerencia.opciones) == 2


class TestEscaleraDeRespaldo:
    """Los tres escalones: (ciudad, barrio) → solo ciudad → sin sugerencia."""

    def test_primer_escalon_ciudad_y_barrio(self) -> None:
        sugerencia = SugeridorDeZona(VECINDARIO).sugerir("TUNJA", "MALDONADO")

        assert sugerencia is not None
        assert sugerencia.confianza is ConfianzaSugerencia.BARRIO
        assert sugerencia.total_vecinos == 1  # solo el vecino de MALDONADO

    def test_segundo_escalon_cuando_el_barrio_no_casa_con_ninguno(self) -> None:
        """Barrio nuevo en una ciudad conocida: se vota con toda la ciudad y se
        dice que el barrio no coincidió, porque la confianza es otra."""
        sugerencia = SugeridorDeZona(VECINDARIO).sugerir("TUNJA", "BARRIO QUE NO EXISTE")

        assert sugerencia is not None
        assert sugerencia.confianza is ConfianzaSugerencia.CIUDAD
        assert sugerencia.total_vecinos == len(VECINDARIO)
        assert "el barrio no coincidió" in sugerencia.confianza.descripcion

    def test_segundo_escalon_tambien_cuando_el_cliente_viene_sin_barrio(self) -> None:
        sugerencia = SugeridorDeZona(VECINDARIO).sugerir("TUNJA", None)

        assert sugerencia is not None
        assert sugerencia.confianza is ConfianzaSugerencia.CIUDAD

    def test_tercer_escalon_sin_sugerencia(self) -> None:
        """Ciudad desconocida: no se adivina. La pantalla lo dice y se asigna a mano."""
        assert SugeridorDeZona(VECINDARIO).sugerir("MEDELLIN", "LAURELES") is None

    def test_la_normalizacion_resuelve_tildes_y_espacios_en_el_primer_escalon(self) -> None:
        """No hace falta un escalón aparte para el barrio "normalizado": el
        primero ya compara sobre el texto normalizado."""
        con_tildes = SugeridorDeZona(VECINDARIO).sugerir("15001 - Tunjá", "  Céntro ")
        directo = SugeridorDeZona(VECINDARIO).sugerir("TUNJA", "CENTRO")

        assert con_tildes is not None and directo is not None
        assert con_tildes.confianza is ConfianzaSugerencia.BARRIO
        assert con_tildes.total_vecinos == directo.total_vecinos


class TestPorcentajes:
    def test_el_porcentaje_es_sobre_los_vecinos_del_escalon(self) -> None:
        sugerencia = SugeridorDeZona(VECINDARIO).sugerir("TUNJA", "CENTRO")

        assert sugerencia is not None
        assert sugerencia.opciones[0].porcentaje == 0.75  # 3 de 4
        assert sum(opcion.porcentaje for opcion in sugerencia.opciones) == 1.0

    def test_una_sola_zona_se_lleva_el_cien_por_ciento(self) -> None:
        sugerencia = SugeridorDeZona(VECINDARIO).sugerir("TUNJA", "LAS NIEVES")

        assert sugerencia is not None
        assert sugerencia.opciones[0].porcentaje == 1.0


class TestVecinosDeEjemplo:
    def test_muestra_hasta_tres_vecinos_con_su_direccion(self) -> None:
        vecinos = [
            Cliente(
                codigo=str(numero),
                ciudad="TUNJA",
                barrio="CENTRO",
                zona=ZONA_CENTRO,
                razon_social=f"TIENDA {numero}",
                direccion=f"CL {numero} 2 3",
            )
            for numero in range(1, 6)
        ]

        sugerencia = SugeridorDeZona(vecinos).sugerir("TUNJA", "CENTRO")

        assert sugerencia is not None
        ejemplos = sugerencia.opciones[0].ejemplos
        assert len(ejemplos) == 3  # son 5 vecinos, se muestran 3
        assert ejemplos[0].etiqueta == "TIENDA 1 — CL 1 2 3"

    def test_los_vecinos_con_direccion_van_primero(self) -> None:
        """Un vecino sin dirección no sirve para reconocer la calle."""
        vecinos = [
            Cliente(codigo="1", ciudad="TUNJA", barrio="CENTRO", zona=ZONA_CENTRO, razon_social="SIN CALLE"),
            Cliente(
                codigo="2",
                ciudad="TUNJA",
                barrio="CENTRO",
                zona=ZONA_CENTRO,
                razon_social="CON CALLE",
                direccion="CL 1 2 3",
            ),
        ]

        sugerencia = SugeridorDeZona(vecinos).sugerir("TUNJA", "CENTRO")

        assert sugerencia is not None
        assert [e.nombre for e in sugerencia.opciones[0].ejemplos] == ["CON CALLE", "SIN CALLE"]

    def test_un_vecino_sin_nombre_se_muestra_por_su_codigo(self) -> None:
        vecinos = [Cliente(codigo="200001", ciudad="TUNJA", barrio="CENTRO", zona=ZONA_CENTRO)]

        sugerencia = SugeridorDeZona(vecinos).sugerir("TUNJA", "CENTRO")

        assert sugerencia is not None
        assert sugerencia.opciones[0].ejemplos[0].etiqueta == "200001 — sin dirección"

    def test_cada_zona_trae_sus_propios_vecinos(self) -> None:
        """Los ejemplos tienen que ser de la zona que acompañan, no del montón."""
        sugerencia = SugeridorDeZona(VECINDARIO).sugerir("TUNJA", "CENTRO")

        assert sugerencia is not None
        de_centro = {e.codigo for e in sugerencia.opciones[0].ejemplos}
        de_nieves = {e.codigo for e in sugerencia.opciones[1].ejemplos}
        assert de_centro == {"1", "2", "3"}
        assert de_nieves == {"4"}
