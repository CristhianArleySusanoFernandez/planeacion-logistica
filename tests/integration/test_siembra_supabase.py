"""Prueba de integración opcional: solo corre si hay credenciales de Supabase.

Requiere haber aplicado migrations/001_esquema_inicial.sql en el proyecto.
"""

import pytest
from pydantic import ValidationError

from planeacion.domain.modelo import Municipio


def _hay_credenciales() -> bool:
    try:
        from planeacion.config.settings import Settings

        Settings()
        return True
    except ValidationError:
        return False


@pytest.mark.integration
@pytest.mark.skipif(not _hay_credenciales(), reason="sin SUPABASE_URL/SUPABASE_KEY (ni .env)")
def test_upsert_idempotente_de_municipios() -> None:
    from planeacion.config.contenedor import crear_contenedor

    contenedor = crear_contenedor()
    lote = [Municipio(nombre="OTROS")]

    ids_primera = contenedor.municipios.guardar_lote(lote)
    ids_segunda = contenedor.municipios.guardar_lote(lote)

    assert "OTROS" in ids_primera
    # Idempotente: re-sembrar no crea otra fila ni cambia el id.
    assert ids_primera["OTROS"] == ids_segunda["OTROS"]
    assert any(m.nombre == "OTROS" for m in contenedor.municipios.listar())
