"""El repertorio depende del día de la semana.

La misma zona no siempre la atiende el mismo carro: en el histórico
(TUNJA): ASIS va en el 13 casi toda la semana pero en el 12 los jueves, y
(BARBOSA): MUNICIPIO CITE va en el 5 salvo los sábados. El día se resuelve en el
CASO DE USO, que le pasa al ``Balanceador`` solo el repertorio de ese día: por eso
el balanceador sigue viendo un mapa plano carro → zonas y estas pruebas cruzan el
caso de uso, no el servicio de dominio.
"""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from planeacion.application.casos_uso.generar_planeacion import CasoDeUsoGenerarPlaneacion
from planeacion.application.dto.pivote import PivotePorZonaDTO, ZonaAgregadaDTO
from planeacion.application.puertos.salida.repositorios import ParRepertorio
from planeacion.domain.modelo import Carro, ReglasBalanceo, ResultadoBalanceo
from planeacion.domain.servicios.parseo_zonas import crear_zona

_ASIS = "(TUNJA): ASIS"
_NIEVES = "(TUNJA): NIEVES"

# Jueves y viernes de la misma semana: lo único que cambia entre las dos corridas.
_JUEVES = date(2026, 7, 9)
_VIERNES = date(2026, 7, 10)

# Lo que dice el histórico: ASIS va en el 13, salvo los jueves que va en el 12.
_REPERTORIO = {
    "jueves": {"12": {_ASIS}, "13": {_NIEVES}},
    "viernes": {"13": {_ASIS, _NIEVES}},
    "sabado": {"13": {_NIEVES}},  # ASIS no la atiende nadie los sábados
}


class _PivoteFalso:
    def __init__(self, fecha: date) -> None:
        self._fecha = fecha

    def ejecutar(
        self, ruta_ecom: Path, fecha: date | None = None, todas_las_fechas: bool = False
    ) -> PivotePorZonaDTO:
        zonas = tuple(
            ZonaAgregadaDTO(
                zona=nombre,
                municipio="TUNJA",
                facturas=10,
                clientes=10,
                pesos=Decimal("1000"),
                kilos=Decimal("5"),
            )
            for nombre in (_ASIS, _NIEVES)
        )
        return PivotePorZonaDTO(
            fecha=self._fecha,
            zonas=zonas,
            total_facturas=20,
            total_clientes=20,
            total_pesos=Decimal("2000"),
            total_kilos=Decimal("10"),
            no_resueltos=(),
            facturas_no_resueltas=0,
            pesos_no_resueltos=Decimal("0"),
            kilos_no_resueltos=Decimal("0"),
            pedidos_excluidos_por_fecha=0,
            fechas_excluidas=(),
        )


class _CarrosFalso:
    def listar(self) -> list[Carro]:
        from planeacion.domain.modelo import Municipio

        return [Carro(numero=n, municipio=Municipio(nombre="TUNJA")) for n in ("12", "13")]


class _ZonasFalso:
    def listar(self) -> list[object]:
        return [crear_zona(_ASIS), crear_zona(_NIEVES)]


class _PlaneacionesFalso:
    def obtener_asignacion_previa(self, dia_semana: str) -> None:
        return None


class _CarroZonasFalso:
    """Registra qué día se le pidió: es la mitad del contrato que se está probando."""

    def __init__(self, por_dia: dict[str, dict[str, set[str]]]) -> None:
        self._por_dia = por_dia
        self.dias_pedidos: list[str] = []

    def obtener_por_dia(self, dia_semana: str) -> dict[str, set[str]]:
        self.dias_pedidos.append(dia_semana)
        return {carro: set(zonas) for carro, zonas in self._por_dia.get(dia_semana, {}).items()}

    def frecuencias(self) -> dict[ParRepertorio, int]:
        """Estas pruebas miran el día, no la costumbre: sin frecuencias el desempate
        por frecuencia no entra y el reparto lo decide solo el balance."""
        return {}


def _planear(fecha: date, repertorio: dict[str, dict[str, set[str]]]) -> ResultadoBalanceo:
    carro_zonas = _CarroZonasFalso(repertorio)
    caso = CasoDeUsoGenerarPlaneacion(
        pivote=_PivoteFalso(fecha),  # type: ignore[arg-type]  # dobles estructurales
        carros=_CarrosFalso(),  # type: ignore[arg-type]
        zonas=_ZonasFalso(),  # type: ignore[arg-type]
        planeaciones=_PlaneacionesFalso(),  # type: ignore[arg-type]
        carro_zonas=carro_zonas,  # type: ignore[arg-type]
    )
    planeacion = caso.ejecutar(Path("ecom.xlsx"), reglas=ReglasBalanceo(max_iteraciones=0))
    assert carro_zonas.dias_pedidos == [_dia_de(fecha)]
    return planeacion.resultado


def _dia_de(fecha: date) -> str:
    from planeacion.domain.modelo import dia_de

    return dia_de(fecha)


def _carro_de(resultado: ResultadoBalanceo, nombre_zona: str) -> str | None:
    for cargas in resultado.cargas_por_municipio.values():
        for carga in cargas:
            if any(zona.zona.nombre == nombre_zona for zona in carga.zonas):
                return carga.carro.numero
    return None


def test_la_misma_zona_cae_en_carros_distintos_segun_el_dia() -> None:
    """El caso concreto medido: ASIS va en el 13, pero los jueves en el 12."""
    assert _carro_de(_planear(_JUEVES, _REPERTORIO), _ASIS) == "12"
    assert _carro_de(_planear(_VIERNES, _REPERTORIO), _ASIS) == "13"


def test_una_zona_sin_carro_elegible_ese_dia_queda_sin_asignar() -> None:
    """Los sábados nadie atiende ASIS: se reporta, no se fuerza a un carro cualquiera."""
    resultado = _planear(date(2026, 7, 11), _REPERTORIO)  # sábado

    assert [z.zona.nombre for z in resultado.zonas_sin_carro] == [_ASIS]
    assert _carro_de(resultado, _ASIS) is None
    assert _carro_de(resultado, _NIEVES) == "13"


def test_sin_repertorio_para_ese_dia_se_balancea_como_antes() -> None:
    """Regresión: con la tabla vacía cualquier carro del municipio sirve."""
    resultado = _planear(_JUEVES, {})

    assert list(resultado.zonas_sin_carro) == []
    assert _carro_de(resultado, _ASIS) is not None
    assert _carro_de(resultado, _NIEVES) is not None


def test_el_dia_pedido_sale_de_la_fecha_del_pivote_y_no_de_otra_cosa() -> None:
    carro_zonas = _CarroZonasFalso(_REPERTORIO)
    caso = CasoDeUsoGenerarPlaneacion(
        pivote=_PivoteFalso(_JUEVES),  # type: ignore[arg-type]
        carros=_CarrosFalso(),  # type: ignore[arg-type]
        zonas=_ZonasFalso(),  # type: ignore[arg-type]
        planeaciones=_PlaneacionesFalso(),  # type: ignore[arg-type]
        carro_zonas=carro_zonas,  # type: ignore[arg-type]
    )

    planeacion = caso.ejecutar(Path("ecom.xlsx"), reglas=ReglasBalanceo(max_iteraciones=0))

    assert planeacion.dia_semana == "jueves"
    assert carro_zonas.dias_pedidos == ["jueves"]


@pytest.mark.parametrize(
    ("fecha", "esperado"),
    [
        (date(2026, 7, 6), "lunes"),
        (date(2026, 7, 11), "sabado"),
        (date(2026, 7, 12), "domingo"),
    ],
)
def test_el_nombre_del_dia_sale_en_minusculas_y_sin_tildes(fecha: date, esperado: str) -> None:
    """Es la forma en que viaja a la base (columna dia_semana) y se compara."""
    assert _dia_de(fecha) == esperado
