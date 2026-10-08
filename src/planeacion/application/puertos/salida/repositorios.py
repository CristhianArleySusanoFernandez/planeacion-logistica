"""Puertos de salida: interfaces de los repositorios que implementa la infraestructura.

Los ids de base de datos son detalle de persistencia y no entran al dominio: los
métodos de guardado devuelven/reciben mapas ``clave natural → id`` solo para que
la siembra pueda resolver las llaves foráneas en el borde.
"""

from collections.abc import Mapping, Sequence
from datetime import date
from typing import NamedTuple, Protocol

from planeacion.application.dto.planeacion import AsignacionPrevia
from planeacion.domain.modelo import (
    AsignacionZona,
    Carro,
    Cliente,
    CorreccionUbicacion,
    Municipio,
    OverrideZona,
    Zona,
)
from planeacion.domain.servicios.auditoria_zonas import ReferenciasMovidas


class RepositorioMunicipios(Protocol):
    def guardar_lote(self, municipios: Sequence[Municipio]) -> dict[str, int]:
        """Upsert por nombre. Devuelve el mapa nombre → id persistido."""
        ...

    def listar(self) -> list[Municipio]: ...


class RepositorioZonas(Protocol):
    def guardar_lote(self, zonas: Sequence[Zona], ids_municipios: Mapping[str, int]) -> dict[str, int]:
        """Upsert por nombre. Devuelve el mapa nombre → id persistido."""
        ...

    def obtener_por_nombre(self, nombre: str) -> Zona | None: ...

    def listar(self) -> list[Zona]: ...

    def actualizar_zona(self, zona: Zona) -> None:
        """Upsert por nombre: actualiza la zona (municipio, regla, activa) o la crea si no existe."""
        ...

    def eliminar_zona(self, nombre: str) -> None:
        """Borra la zona. LookupError si no existe; ValueError si tiene referencias
        (clientes, overrides o planeaciones) — en ese caso conviene desactivarla."""
        ...

    def fusionar_zona(self, nombre_variante: str, nombre_canonica: str) -> ReferenciasMovidas:
        """Reapunta a la zona canónica todo lo que referencia a la variante
        (clientes, repertorio, overrides e histórico de planeaciones), borra la
        variante ya vacía y devuelve cuántas filas movió. El repertorio no
        duplica el par (carro, zona) si el carro ya tenía la canónica.
        LookupError si alguno de los dos nombres no existe."""
        ...


class RepositorioCarros(Protocol):
    def guardar_lote(self, carros: Sequence[Carro], ids_municipios: Mapping[str, int]) -> int:
        """Upsert por numero. Devuelve cuántos carros guardó."""
        ...

    def listar(self) -> list[Carro]: ...

    def actualizar_carro(self, carro: Carro) -> None:
        """Upsert por numero: actualiza el carro (conductor, municipio, activo...) o lo crea."""
        ...

    def eliminar_carro(self, numero: str) -> None:
        """Borra el carro. LookupError si no existe; ValueError si tiene planeaciones
        que lo referencian — en ese caso conviene desactivarlo (su repertorio sí se borra)."""
        ...


class RepositorioClientes(Protocol):
    def guardar_lote(self, clientes: Sequence[Cliente], ids_zonas: Mapping[str, int]) -> int:
        """Upsert por codigo. Devuelve cuántos clientes guardó."""
        ...

    def listar(self) -> list[Cliente]:
        """Todos los clientes con su zona ya cargada (para construir el resolutor)."""
        ...

    def guardar_cliente(self, cliente: Cliente) -> None:
        """Upsert de UN cliente (el nuevo que Rudy aprobó); la zona se resuelve por nombre."""
        ...

    def actualizar_zona(self, codigo: str, zona_nombre: str) -> None:
        """Cambia solo la zona de un cliente existente (estaba en la maestra sin RUTA)."""
        ...

    def contar(self) -> int: ...


class RepositorioCorrecciones(Protocol):
    def guardar_lote(self, correcciones: Sequence[CorreccionUbicacion]) -> int:
        """Upsert por cliente_codigo. Devuelve cuántas correcciones guardó."""
        ...

    def listar(self) -> list[CorreccionUbicacion]: ...

    def guardar_correccion(self, correccion: CorreccionUbicacion) -> None:
        """Upsert de UNA corrección (alta o edición desde la pantalla de configuración)."""
        ...

    def eliminar(self, cliente_codigo: str) -> None: ...


class RepositorioOverrides(Protocol):
    def guardar_lote(self, overrides: Sequence[OverrideZona], ids_zonas: Mapping[str, int]) -> int:
        """Upsert por cliente_codigo. Devuelve cuántos overrides guardó."""
        ...

    def listar(self) -> list[OverrideZona]: ...

    def guardar_override(self, override: OverrideZona) -> None:
        """Upsert de UN override; la zona se resuelve por nombre (LookupError si no existe)."""
        ...

    def eliminar(self, cliente_codigo: str) -> None: ...


class ParRepertorio(NamedTuple):
    """Una fila del repertorio: este carro atiende esta zona este día.

    ``frecuencia`` es cuántas veces se observó el par en el histórico; 0 es "lo
    puso alguien a mano, nunca se vio". Deja distinguir una regla estable de un
    reemplazo puntual, que es lo que la usuaria decide en la interfaz.
    """

    numero_carro: str
    nombre_zona: str
    dia_semana: str
    frecuencia: int = 0


class RepositorioCarroZonas(Protocol):
    """El repertorio: qué zonas puede atender cada carro, por día de la semana
    (tabla carro_zonas). Una zona-día con un solo carro queda fijada; con varios,
    el balanceador elige entre ellos."""

    def obtener_por_dia(self, dia_semana: str) -> dict[str, set[str]]:
        """Número de carro → zonas permitidas ESE día. {} si no hay nada configurado.

        Es lo único que necesita el balanceo: el caso de uso ya sabe la fecha, así
        que resuelve el día acá y el ``Balanceador`` sigue viendo un repertorio
        plano, sin enterarse de que existen los días.
        """
        ...

    def obtener_matriz(self) -> dict[str, dict[str, set[str]]]:
        """Día → carro → zonas permitidas. Para las pantallas de configuración,
        que muestran un día pero necesitan poder copiar de otro."""
        ...

    def frecuencias(self) -> dict[ParRepertorio, int]:
        """(carro, zona, día) → veces observado en el histórico. Lo usa la matriz
        para marcar los pares vistos una sola vez, que suelen ser reemplazos."""
        ...

    def asignar(self, numero_carro: str, nombre_zona: str, dia_semana: str) -> None:
        """Agrega una zona al repertorio del carro para ese día (idempotente).
        LookupError si el carro o la zona no existen en la base."""
        ...

    def asignar_lote(self, pares: Sequence[ParRepertorio]) -> int:
        """Upsert idempotente de pares ya validados; la frecuencia se pisa con la
        del par. Devuelve cuántos pares intentó sembrar. LookupError si algo no existe."""
        ...

    def quitar(self, numero_carro: str, nombre_zona: str, dia_semana: str) -> None: ...

    def vaciar(self) -> int:
        """Borra TODO el repertorio y devuelve cuántos pares borró.

        Es para cuando la numeración de las rutas cambió de significado: en octubre
        de 2026 la ruta 13 pasó de ser de Tunja a ser Villa de Leyva, así que cada
        par viejo habilita una combinación que nunca existió. Fusionar o borrar solo
        lo de frecuencia 0 dejaría sobrevivientes inválidos; hay que vaciar.
        DESTRUCTIVO: quien lo llame respalda antes.
        """
        ...

    def quitar_sin_observaciones(self) -> int:
        """Borra los pares con ``frecuencia = 0`` y devuelve cuántos borró.

        Son los que no salieron de ningún histórico: configuración puesta a mano o
        restos del backfill de la migración 003, que replicó a los seis días lo que
        estaba sin día. Mientras siguen ahí habilitan combinaciones que el
        histórico nunca vio y diluyen la dimensión del día, pero borrarlos es
        destructivo, así que solo lo pide explícitamente la siembra con
        ``--borrar-frecuencia-cero``.
        """
        ...


class RepositorioPlaneaciones(Protocol):
    def guardar_planeacion(self, fecha: date, dia_semana: str, asignaciones: Sequence[AsignacionZona]) -> int:
        """Inserta la cabecera y el detalle zona→carro. Devuelve el id de la planeación."""
        ...

    def obtener_asignacion_previa(self, dia_semana: str) -> AsignacionPrevia | None:
        """La fecha y el mapeo zona→carro de la planeación más reciente con ese día
        de semana (incluida la de hoy si ya se guardó); None si no hay ninguna."""
        ...
