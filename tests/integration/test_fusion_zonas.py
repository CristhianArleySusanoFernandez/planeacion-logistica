"""Prueba de integración de la fusión de zonas duplicadas.

Crea dos zonas centinela que normalizan al mismo nombre (una con espacios de
más), les cuelga repertorio y un override, las fusiona y verifica que todo
quedó apuntando a la canónica sin duplicar el par (carro, zona, día). Limpia al
final pase lo que pase, para no dejar basura en la base real.
"""

from typing import Any

import pytest
from pydantic import ValidationError

# Nombres centinela: normalizan ambos a "(PRUEBA): FUSION" y no chocan con datos reales.
_CANONICA = "(PRUEBA): FUSION"
_VARIANTE = "(PRUEBA):   FUSION"
_CLIENTE_CENTINELA = "ZZZ-PRUEBA-FUSION"


def _hay_credenciales() -> bool:
    try:
        from planeacion.config.settings import Settings

        Settings()
        return True
    except ValidationError:
        return False


def _hay_dimension_de_dia(cliente: Any) -> bool:
    """¿Está aplicada la migración 003? El repertorio se maneja por día desde
    entonces, y sin la columna el escenario de esta prueba no se puede montar."""
    try:
        cliente.table("carro_zonas").select("dia_semana").limit(1).execute()
        return True
    except Exception:
        return False


def _limpiar(cliente: Any, ids_zonas: list[int]) -> None:
    if ids_zonas:
        cliente.table("carro_zonas").delete().in_("zona_id", ids_zonas).execute()
        cliente.table("overrides_zona").delete().in_("zona_id", ids_zonas).execute()
        cliente.table("clientes").delete().eq("codigo", _CLIENTE_CENTINELA).execute()
        cliente.table("zonas").delete().in_("id", ids_zonas).execute()


@pytest.mark.integration
@pytest.mark.skipif(not _hay_credenciales(), reason="sin SUPABASE_URL/SUPABASE_KEY (ni .env)")
def test_fusionar_reapunta_todo_y_no_duplica_el_repertorio() -> None:
    from planeacion.config.contenedor import crear_cliente_supabase, crear_contenedor
    from planeacion.config.settings import Settings
    from planeacion.domain.modelo import OverrideZona, Zona
    from planeacion.domain.servicios.auditoria_zonas import agrupar_duplicados

    settings = Settings()
    cliente = crear_cliente_supabase(settings)
    contenedor = crear_contenedor(settings)
    if not _hay_dimension_de_dia(cliente):
        pytest.skip("falta aplicar migrations/003_carro_zonas_dia.sql en Supabase")

    municipio = contenedor.municipios.listar()[0]
    carros = contenedor.carros.listar()[:2]
    assert len(carros) == 2, "la BD debe estar sembrada"

    ids_zonas: list[int] = []
    try:
        # Dos zonas que solo se diferencian en el espaciado.
        for nombre in (_CANONICA, _VARIANTE):
            contenedor.zonas.actualizar_zona(Zona(nombre=nombre, municipio=municipio))
        filas = cliente.table("zonas").select("id, nombre").in_("nombre", [_CANONICA, _VARIANTE]).execute()
        por_nombre = {f["nombre"]: int(f["id"]) for f in filas.data}
        ids_zonas = list(por_nombre.values())
        assert len(ids_zonas) == 2

        # carro[0] tiene AMBAS el lunes (el par colisiona al fusionar); carro[1]
        # solo la variante. Y carro[0] tiene la variante también el MARTES, día en
        # que no tiene la canónica: esa fila tiene que sobrevivir a la fusión, no
        # ser absorbida por la colisión del lunes.
        contenedor.carro_zonas.asignar(carros[0].numero, _CANONICA, "lunes")
        contenedor.carro_zonas.asignar(carros[0].numero, _VARIANTE, "lunes")
        contenedor.carro_zonas.asignar(carros[0].numero, _VARIANTE, "martes")
        contenedor.carro_zonas.asignar(carros[1].numero, _VARIANTE, "lunes")

        # Un cliente y un override colgando de la variante.
        cliente.table("clientes").upsert(
            {"codigo": _CLIENTE_CENTINELA, "zona_id": por_nombre[_VARIANTE]}, on_conflict="codigo"
        ).execute()
        contenedor.overrides.guardar_override(
            OverrideZona(cliente_codigo=_CLIENTE_CENTINELA, zona_nombre=_VARIANTE)
        )

        # La elección de canónica se prueba aparte (test_auditoria_zonas); aquí se
        # fija a mano para probar el movimiento de referencias.
        movidas = contenedor.zonas.fusionar_zona(_VARIANTE, _CANONICA)

        assert movidas.clientes == 1
        assert movidas.overrides == 1
        assert movidas.repertorio == 3  # tres pares (carro, día) tenían la variante

        # La variante ya no existe.
        restantes = cliente.table("zonas").select("nombre").in_("nombre", [_CANONICA, _VARIANTE]).execute()
        assert [f["nombre"] for f in restantes.data] == [_CANONICA]

        # El repertorio quedó sin duplicados: un solo par por (carro, día) con la
        # canónica, y el martes del carro[0] sobrevivió.
        pares = (
            cliente.table("carro_zonas")
            .select("carro_id, dia_semana")
            .eq("zona_id", por_nombre[_CANONICA])
            .execute()
        )
        claves = [(int(f["carro_id"]), f["dia_semana"]) for f in pares.data]
        assert len(claves) == len(set(claves)) == 3
        assert sorted(dia for _, dia in claves) == ["lunes", "lunes", "martes"]

        # Cliente y override apuntan a la canónica.
        fila_cliente = cliente.table("clientes").select("zona_id").eq("codigo", _CLIENTE_CENTINELA).execute()
        assert int(fila_cliente.data[0]["zona_id"]) == por_nombre[_CANONICA]

        # Y la auditoría posterior ya no reporta el grupo.
        zonas = [z for z in contenedor.zonas.listar() if z.nombre in (_CANONICA, _VARIANTE)]
        assert agrupar_duplicados(zonas, {}) == []
    finally:
        _limpiar(cliente, ids_zonas)
