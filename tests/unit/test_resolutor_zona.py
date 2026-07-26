"""Pruebas del ResolutorDeZona: prioridad override → maestra → no resuelto."""

from planeacion.domain.modelo import MotivoNoResuelto
from planeacion.domain.servicios.parseo_zonas import crear_zona
from planeacion.domain.servicios.resolutor_zona import ResolutorDeZona

ZONA_NIEVES = crear_zona("(TUNJA):  NIEVES")
ZONA_FORZADA = crear_zona("(BARBOSA):  BARBOSA-PUENTE")


def test_la_maestra_resuelve_cuando_no_hay_override() -> None:
    resolutor = ResolutorDeZona(zonas_maestra={"8043": ZONA_NIEVES}, zonas_override={})

    assert resolutor.resolver("8043") == ZONA_NIEVES


def test_el_override_gana_sobre_la_maestra() -> None:
    resolutor = ResolutorDeZona(
        zonas_maestra={"8043": ZONA_NIEVES},
        zonas_override={"8043": ZONA_FORZADA},
    )

    assert resolutor.resolver("8043") == ZONA_FORZADA


def test_el_override_aplica_aunque_el_cliente_no_este_en_la_maestra() -> None:
    resolutor = ResolutorDeZona(zonas_maestra={}, zonas_override={"9999": ZONA_FORZADA})

    assert resolutor.resolver("9999") == ZONA_FORZADA


def test_cliente_desconocido_no_resuelve_y_es_nd() -> None:
    resolutor = ResolutorDeZona(zonas_maestra={"8043": ZONA_NIEVES}, zonas_override={})

    assert resolutor.resolver("0000") is None
    assert resolutor.motivo_no_resuelto("0000") == MotivoNoResuelto.NO_ESTA_EN_MAESTRA


def test_cliente_en_maestra_sin_ruta_no_resuelve_pero_no_es_nd() -> None:
    # El "(en blanco)" del pivote viejo: está en la maestra pero su RUTA venía vacía.
    resolutor = ResolutorDeZona(zonas_maestra={"7001": None}, zonas_override={})

    assert resolutor.resolver("7001") is None
    assert resolutor.motivo_no_resuelto("7001") == MotivoNoResuelto.EN_MAESTRA_SIN_ZONA
