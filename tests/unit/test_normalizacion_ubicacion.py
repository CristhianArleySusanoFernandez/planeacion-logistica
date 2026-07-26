"""Pruebas de la normalización de ubicaciones (ciudad/barrio)."""

from planeacion.domain.servicios.normalizacion_ubicacion import normalizar_ubicacion


def test_quita_el_prefijo_dane_del_ecom() -> None:
    # La maestra guarda "TUNJA"; el ECOM trae "15001 - TUNJA". Deben casar.
    assert normalizar_ubicacion("15001 - TUNJA") == "TUNJA"
    assert normalizar_ubicacion("15001-TUNJA") == "TUNJA"


def test_quita_acentos() -> None:
    assert normalizar_ubicacion("Moniquirá") == "MONIQUIRA"
    assert normalizar_ubicacion("BOGOTÁ") == "BOGOTA"


def test_mayusculas_y_espacios_colapsados() -> None:
    assert normalizar_ubicacion("  santa   ana  ") == "SANTA ANA"


def test_none_y_vacio_quedan_vacios() -> None:
    assert normalizar_ubicacion(None) == ""
    assert normalizar_ubicacion("   ") == ""


def test_texto_ya_normalizado_no_cambia() -> None:
    assert normalizar_ubicacion("TUNJA") == "TUNJA"


def test_no_confunde_guiones_internos_con_el_prefijo_dane() -> None:
    # Solo se quita el prefijo si empieza con dígitos; un nombre con guion queda igual.
    assert normalizar_ubicacion("BARBOSA - CENTRO") == "BARBOSA - CENTRO"
