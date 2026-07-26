"""Pruebas del caso de uso ResolverClientesNuevos con repositorios falsos en memoria."""

from collections.abc import Mapping, Sequence

import pytest

from planeacion.application.casos_uso.resolver_clientes_nuevos import CasoDeUsoResolverClientesNuevos
from planeacion.application.dto.pivote import ClienteNoResueltoDTO
from planeacion.domain.errores import ZonaInexistente
from planeacion.domain.modelo import Cliente, CorreccionUbicacion, Zona
from planeacion.domain.servicios.parseo_zonas import crear_zona

ZONA_CENTRO = crear_zona("(TUNJA):  RUTA CENTRO 1")
ZONA_NIEVES = crear_zona("(TUNJA):  NIEVES")


class RepoClientesFalso:
    def __init__(self, clientes: list[Cliente]) -> None:
        self._clientes = clientes
        self.guardados: list[Cliente] = []
        self.zonas_actualizadas: list[tuple[str, str]] = []

    def guardar_lote(self, clientes: Sequence[Cliente], ids_zonas: Mapping[str, int]) -> int:
        raise NotImplementedError

    def obtener_por_codigo(self, codigo: str) -> Cliente | None:
        raise NotImplementedError

    def listar(self) -> list[Cliente]:
        return list(self._clientes)

    def guardar_cliente(self, cliente: Cliente) -> None:
        self.guardados.append(cliente)

    def actualizar_zona(self, codigo: str, zona_nombre: str) -> None:
        self.zonas_actualizadas.append((codigo, zona_nombre))

    def contar(self) -> int:
        return len(self._clientes)


class RepoZonasFalso:
    def __init__(self, zonas: list[Zona]) -> None:
        self._zonas = zonas

    def guardar_lote(self, zonas: Sequence[Zona], ids_municipios: Mapping[str, int]) -> dict[str, int]:
        raise NotImplementedError

    def obtener_por_nombre(self, nombre: str) -> Zona | None:
        return next((z for z in self._zonas if z.nombre == nombre), None)

    def listar(self) -> list[Zona]:
        return list(self._zonas)


class RepoCorreccionesFalso:
    def __init__(self, correcciones: list[CorreccionUbicacion]) -> None:
        self._correcciones = correcciones

    def guardar_lote(self, correcciones: Sequence[CorreccionUbicacion]) -> int:
        raise NotImplementedError

    def listar(self) -> list[CorreccionUbicacion]:
        return list(self._correcciones)


def _no_resuelto(
    codigo: str,
    motivo: str = "NO_ESTA_EN_MAESTRA",
    ciudad: str | None = "15001 - TUNJA",
    barrio: str | None = "CENTRO",
) -> ClienteNoResueltoDTO:
    return ClienteNoResueltoDTO(
        codigo=codigo,
        motivo=motivo,
        nombre="TIENDA NUEVA",
        documento="900123",
        direccion="CL 1 # 2-3",
        ciudad=ciudad,
        barrio=barrio,
    )


def _caso_uso(
    clientes: RepoClientesFalso | None = None,
    correcciones: list[CorreccionUbicacion] | None = None,
) -> tuple[CasoDeUsoResolverClientesNuevos, RepoClientesFalso]:
    repo_clientes = clientes or RepoClientesFalso(
        [
            Cliente(codigo="1", ciudad="TUNJA", barrio="CENTRO", zona=ZONA_CENTRO),
            Cliente(codigo="2", ciudad="TUNJA", barrio="CENTRO", zona=ZONA_CENTRO),
            Cliente(codigo="3", ciudad="TUNJA", barrio="CENTRO", zona=ZONA_NIEVES),
        ]
    )
    caso_uso = CasoDeUsoResolverClientesNuevos(
        clientes=repo_clientes,
        zonas=RepoZonasFalso([ZONA_CENTRO, ZONA_NIEVES]),
        correcciones=RepoCorreccionesFalso(correcciones or []),
    )
    return caso_uso, repo_clientes


def test_pendientes_trae_la_sugerencia_del_voto_de_vecinos() -> None:
    caso_uso, _ = _caso_uso()

    pendientes = caso_uso.pendientes([_no_resuelto("9000")])

    assert len(pendientes) == 1
    sugerencia = pendientes[0].sugerencia
    assert sugerencia is not None
    assert sugerencia.zona == ZONA_CENTRO.nombre
    assert sugerencia.municipio == "TUNJA"
    assert sugerencia.vecinos_en_zona == 2
    assert sugerencia.total_vecinos == 3
    assert sugerencia.confianza == "barrio"
    assert sugerencia.alternativas == ((ZONA_NIEVES.nombre, 1),)


def test_pendientes_sin_vecinos_no_trae_sugerencia() -> None:
    caso_uso, _ = _caso_uso()

    pendientes = caso_uso.pendientes([_no_resuelto("9000", ciudad="VILLAVICENCIO", barrio="X")])

    assert pendientes[0].sugerencia is None


def test_la_correccion_de_cambios_pisa_la_ubicacion_del_ecom() -> None:
    # ECOM trae al cliente en una ciudad basura, pero CAMBIOS lo corrige a TUNJA.
    correccion = CorreccionUbicacion(cliente_codigo="9000", ciudad_real="TUNJA", barrio_real="CENTRO")
    caso_uso, _ = _caso_uso(correcciones=[correccion])

    pendientes = caso_uso.pendientes([_no_resuelto("9000", ciudad="99999 - NINGUNA", barrio="NADA")])

    assert pendientes[0].ciudad == "TUNJA"
    assert pendientes[0].barrio == "CENTRO"
    assert pendientes[0].sugerencia is not None
    assert pendientes[0].sugerencia.zona == ZONA_CENTRO.nombre


def test_confirmar_cliente_nuevo_lo_guarda_completo_con_su_zona() -> None:
    caso_uso, repo = _caso_uso()
    pendiente = caso_uso.pendientes([_no_resuelto("9000")])[0]

    caso_uso.confirmar_cliente(pendiente, ZONA_CENTRO.nombre)

    assert repo.zonas_actualizadas == []
    assert len(repo.guardados) == 1
    guardado = repo.guardados[0]
    assert guardado.codigo == "9000"
    assert guardado.zona == ZONA_CENTRO
    assert guardado.razon_social == "TIENDA NUEVA"
    assert guardado.documento == "900123"
    assert guardado.direccion == "CL 1 # 2-3"
    assert guardado.ciudad == "TUNJA"  # normalizada: sin el prefijo DANE del ECOM
    assert guardado.barrio == "CENTRO"


def test_confirmar_cliente_en_maestra_sin_zona_solo_actualiza_la_zona() -> None:
    caso_uso, repo = _caso_uso()
    pendiente = caso_uso.pendientes([_no_resuelto("9000", motivo="EN_MAESTRA_SIN_ZONA")])[0]

    caso_uso.confirmar_cliente(pendiente, ZONA_NIEVES.nombre)

    assert repo.guardados == []
    assert repo.zonas_actualizadas == [("9000", ZONA_NIEVES.nombre)]


def test_confirmar_con_zona_inexistente_lanza_error_y_no_persiste() -> None:
    caso_uso, repo = _caso_uso()
    pendiente = caso_uso.pendientes([_no_resuelto("9000")])[0]

    with pytest.raises(ZonaInexistente):
        caso_uso.confirmar_cliente(pendiente, "(TUNJA): ZONA FANTASMA")

    assert repo.guardados == []
    assert repo.zonas_actualizadas == []
