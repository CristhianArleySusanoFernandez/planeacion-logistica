"""Composición de dependencias: fábrica del cliente Supabase y de los repositorios."""

from dataclasses import dataclass
from typing import Any

from supabase import Client, create_client

from planeacion.application.casos_uso.ajustar_asignacion import CasoDeUsoAjustarAsignacion
from planeacion.application.casos_uso.generar_pivote import CasoDeUsoGenerarPivote
from planeacion.application.casos_uso.generar_planeacion import CasoDeUsoGenerarPlaneacion
from planeacion.application.casos_uso.resolver_clientes_nuevos import (
    CasoDeUsoResolverClientesNuevos,
)
from planeacion.application.puertos.entrada.ajustar_asignacion import AjustarAsignacion
from planeacion.application.puertos.entrada.generar_pivote import GenerarPivotePorZona
from planeacion.application.puertos.entrada.generar_planeacion import GenerarPlaneacion
from planeacion.application.puertos.entrada.resolver_clientes_nuevos import (
    ResolverClientesNuevos,
)
from planeacion.application.puertos.salida.exportador_planeacion import ExportadorPlaneacion
from planeacion.application.puertos.salida.lector_pedidos import LectorDePedidos
from planeacion.application.puertos.salida.repositorios import (
    RepositorioCarros,
    RepositorioCarroZonas,
    RepositorioClientes,
    RepositorioCorrecciones,
    RepositorioMunicipios,
    RepositorioOverrides,
    RepositorioParametros,
    RepositorioPlaneaciones,
    RepositorioZonas,
)
from planeacion.config.settings import Settings
from planeacion.infraestructura.adaptadores.salida.excel.exportador_planeacion import (
    ExportadorExcelPlaneacion,
)
from planeacion.infraestructura.adaptadores.salida.excel.lector_ecom import LectorEcomExcel
from planeacion.infraestructura.adaptadores.salida.supabase.repositorio_carro_zonas import (
    RepositorioCarroZonasSupabase,
)
from planeacion.infraestructura.adaptadores.salida.supabase.repositorio_carros import (
    RepositorioCarrosSupabase,
)
from planeacion.infraestructura.adaptadores.salida.supabase.repositorio_clientes import (
    RepositorioClientesSupabase,
)
from planeacion.infraestructura.adaptadores.salida.supabase.repositorio_correcciones import (
    RepositorioCorreccionesSupabase,
)
from planeacion.infraestructura.adaptadores.salida.supabase.repositorio_municipios import (
    RepositorioMunicipiosSupabase,
)
from planeacion.infraestructura.adaptadores.salida.supabase.repositorio_overrides import (
    RepositorioOverridesSupabase,
)
from planeacion.infraestructura.adaptadores.salida.supabase.repositorio_parametros import (
    RepositorioParametrosSupabase,
)
from planeacion.infraestructura.adaptadores.salida.supabase.repositorio_planeaciones import (
    RepositorioPlaneacionesSupabase,
)
from planeacion.infraestructura.adaptadores.salida.supabase.repositorio_zonas import (
    RepositorioZonasSupabase,
)


def crear_cliente_supabase(settings: Settings) -> Client:
    return create_client(settings.supabase_url, settings.supabase_key)


@dataclass(frozen=True)
class Contenedor:
    """Repositorios ya cableados; los tipos son los puertos, no los adaptadores."""

    municipios: RepositorioMunicipios
    zonas: RepositorioZonas
    carros: RepositorioCarros
    carro_zonas: RepositorioCarroZonas
    clientes: RepositorioClientes
    correcciones: RepositorioCorrecciones
    overrides: RepositorioOverrides
    planeaciones: RepositorioPlaneaciones
    parametros: RepositorioParametros


def crear_contenedor(settings: Settings | None = None, cliente: Any | None = None) -> Contenedor:
    """Los repositorios ya cableados.

    ``cliente`` existe para medir: ``planeacion-medir`` pasa un envoltorio que
    cuenta los viajes a la base (ver ``cliente_contado``). La app no lo usa.
    """
    settings = settings or Settings()
    cliente = cliente or crear_cliente_supabase(settings)
    return Contenedor(
        municipios=RepositorioMunicipiosSupabase(cliente),
        zonas=RepositorioZonasSupabase(cliente),
        carros=RepositorioCarrosSupabase(cliente),
        carro_zonas=RepositorioCarroZonasSupabase(cliente),
        clientes=RepositorioClientesSupabase(cliente),
        correcciones=RepositorioCorreccionesSupabase(cliente),
        overrides=RepositorioOverridesSupabase(cliente),
        planeaciones=RepositorioPlaneacionesSupabase(cliente),
        parametros=RepositorioParametrosSupabase(cliente),
    )


def crear_generar_pivote(
    contenedor: Contenedor, lector: LectorDePedidos | None = None
) -> GenerarPivotePorZona:
    """Sin ``lector`` usa el .xlsx suelto de ECOM; ``planeacion-validar`` pasa el
    que lee el bloque embebido en los .xlsm."""
    return CasoDeUsoGenerarPivote(
        lector=lector or LectorEcomExcel(),
        clientes=contenedor.clientes,
        overrides=contenedor.overrides,
        zonas=contenedor.zonas,
    )


def crear_resolver_clientes_nuevos(contenedor: Contenedor) -> ResolverClientesNuevos:
    return CasoDeUsoResolverClientesNuevos(
        clientes=contenedor.clientes,
        zonas=contenedor.zonas,
        correcciones=contenedor.correcciones,
    )


def crear_generar_planeacion(
    contenedor: Contenedor, lector: LectorDePedidos | None = None
) -> GenerarPlaneacion:
    return CasoDeUsoGenerarPlaneacion(
        pivote=crear_generar_pivote(contenedor, lector),
        carros=contenedor.carros,
        zonas=contenedor.zonas,
        planeaciones=contenedor.planeaciones,
        carro_zonas=contenedor.carro_zonas,
    )


def crear_ajustar_asignacion() -> AjustarAsignacion:
    """No necesita contenedor: opera sobre un resultado de balanceo ya en memoria."""
    return CasoDeUsoAjustarAsignacion()


def crear_exportador_planeacion() -> ExportadorPlaneacion:
    return ExportadorExcelPlaneacion()
