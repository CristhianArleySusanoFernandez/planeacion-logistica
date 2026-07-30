"""Prueba de integración del RepositorioPlaneaciones: guardar y leer la previa.

Usa un dia_semana centinela ("dia-de-prueba") para no interferir con el
warm-start real, y borra la cabecera al final (el detalle cae por cascade).
"""

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

_DIA_CENTINELA = "dia-de-prueba"


def _hay_credenciales() -> bool:
    try:
        from planeacion.config.settings import Settings

        Settings()
        return True
    except ValidationError:
        return False


@pytest.mark.integration
@pytest.mark.skipif(not _hay_credenciales(), reason="sin SUPABASE_URL/SUPABASE_KEY (ni .env)")
def test_guardar_y_recuperar_asignacion_previa() -> None:
    from planeacion.config.contenedor import crear_cliente_supabase, crear_contenedor
    from planeacion.config.settings import Settings
    from planeacion.domain.modelo import AsignacionZona

    contenedor = crear_contenedor()
    zonas = contenedor.zonas.listar()[:2]
    carros = contenedor.carros.listar()[:2]
    assert len(zonas) == 2 and len(carros) == 2, "la BD debe estar sembrada"

    asignaciones = [
        AsignacionZona(
            zona=zonas[0],
            carro=carros[0],
            facturas=3,
            clientes=2,
            pesos=Decimal("1000.50"),
            kilos=Decimal("12.345"),
        ),
        AsignacionZona(
            zona=zonas[1],
            carro=carros[1],
            facturas=1,
            clientes=1,
            pesos=Decimal("500"),
            kilos=Decimal("3"),
        ),
    ]

    id_planeacion = contenedor.planeaciones.guardar_planeacion(date(2026, 1, 1), _DIA_CENTINELA, asignaciones)
    try:
        previa = contenedor.planeaciones.obtener_asignacion_previa(_DIA_CENTINELA)
        assert previa is not None
        assert previa.fecha == date(2026, 1, 1)
        assert previa.zona_a_carro == {
            zonas[0].nombre: carros[0].numero,
            zonas[1].nombre: carros[1].numero,
        }
    finally:
        cliente = crear_cliente_supabase(Settings())
        cliente.table("planeaciones").delete().eq("id", id_planeacion).execute()

    assert contenedor.planeaciones.obtener_asignacion_previa(_DIA_CENTINELA) is None
