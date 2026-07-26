"""Cliente y sus ajustes puntuales (corrección de ubicación y override de zona)."""

from dataclasses import dataclass

from planeacion.domain.modelo.zona import Zona


@dataclass(frozen=True)
class Cliente:
    codigo: str
    direccion: str | None = None
    barrio: str | None = None
    ciudad: str | None = None
    zona: Zona | None = None
    documento: str | None = None
    razon_social: str | None = None
    dia_visita: str | None = None
    activo: bool = True


@dataclass(frozen=True)
class CorreccionUbicacion:
    """Corrige la ciudad/barrio que ECOM trae mal para un cliente (hoja CAMBIOS)."""

    cliente_codigo: str
    ciudad_real: str | None
    barrio_real: str | None


@dataclass(frozen=True)
class OverrideZona:
    """Fuerza la zona de un cliente por encima de la maestra (hoja "martha ojo")."""

    cliente_codigo: str
    zona_nombre: str
