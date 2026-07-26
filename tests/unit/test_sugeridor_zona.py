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


def test_gana_la_zona_mayoritaria_del_barrio_con_alternativas() -> None:
    sugerencia = SugeridorDeZona(VECINDARIO).sugerir("TUNJA", "CENTRO")

    assert sugerencia is not None
    assert sugerencia.zona_sugerida == ZONA_CENTRO
    assert sugerencia.vecinos_en_zona == 3
    assert sugerencia.total_vecinos == 4
    assert sugerencia.confianza == ConfianzaSugerencia.BARRIO
    assert sugerencia.alternativas == ((ZONA_NIEVES, 1),)


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


def test_respeta_max_alternativas() -> None:
    vecinos = VECINDARIO + [
        _cliente("7", "TUNJA", "CENTRO", ZONA_OCCIDENTE),
    ]
    sugerencia = SugeridorDeZona(vecinos).sugerir("TUNJA", "CENTRO", max_alternativas=1)

    assert sugerencia is not None
    assert len(sugerencia.alternativas) == 1
