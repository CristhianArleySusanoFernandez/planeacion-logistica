"""El candado del Paso 3 exige dos observaciones (Prompt 26).

Una zona con UNA sola ruta posible ese día:
- vista >= `observaciones_para_fijar` veces, o con frecuencia 0 («este carro no»): FIJA;
- vista menos veces: SUGERIDA, el balanceador la deja ahí pero se puede mover a
  cualquier ruta activa de su municipio.

Las restricciones de elegibilidad (lado de Chiquinquirá, marca única de una
especial) son otra cosa y llevan su propio nombre. El reparto automático no cambia.
"""

from decimal import Decimal

import pytest

from planeacion.domain.errores import MovimientoInvalido
from planeacion.domain.modelo import Carro, NivelDeFijacion, ReglasBalanceo, ResultadoBalanceo, ZonaAgregada
from planeacion.domain.modelo.balanceo import OBSERVACIONES_PARA_FIJAR
from planeacion.domain.servicios.balanceador import AjustadorDeAsignacion, Balanceador
from planeacion.domain.servicios.parseo_zonas import crear_zona

SIN_MEJORA = ReglasBalanceo(max_iteraciones=0)
_CARROS = {
    "TUNJA": [Carro(numero="18"), Carro(numero="19"), Carro(numero="20")],
    "BARBOSA": [Carro(numero="5")],
}


def _zona(nombre: str, especial: bool = False) -> ZonaAgregada:
    zona = crear_zona(nombre)
    if especial:
        zona = type(zona)(nombre=zona.nombre, municipio=zona.municipio, especial=True)
    return ZonaAgregada(zona=zona, facturas=5, clientes=5, pesos=Decimal("100"), kilos=Decimal("1"))


def _repartir(
    frecuencia_unica: int, repertorio_extra: dict[str, set[str]] | None = None
) -> ResultadoBalanceo:
    """UNICA solo en la 18 con la frecuencia dada; DOBLE en la 18 y la 19; una
    especial sin marcas; una zona de Barbosa para tener otro pool."""
    zonas = [
        _zona("(TUNJA): UNICA"),
        _zona("(TUNJA): DOBLE"),
        _zona("(TUNJA): ESPECIAL", especial=True),
        _zona("(BARBOSA): CENTRO"),
    ]
    repertorio = {
        "18": {"(TUNJA): UNICA", "(TUNJA): DOBLE"},
        "19": {"(TUNJA): DOBLE"},
        "5": {"(BARBOSA): CENTRO"},
    }
    for carro, extra in (repertorio_extra or {}).items():
        repertorio.setdefault(carro, set()).update(extra)
    frecuencias = {
        ("18", "(TUNJA): UNICA"): frecuencia_unica,
        ("18", "(TUNJA): DOBLE"): 3,
        ("19", "(TUNJA): DOBLE"): 1,
        ("5", "(BARBOSA): CENTRO"): 4,
    }
    return Balanceador().balancear(zonas, _CARROS, None, SIN_MEJORA, repertorio, frecuencias=frecuencias)


def _carro_de(resultado: ResultadoBalanceo, nombre: str) -> str:
    for cargas in resultado.cargas_por_municipio.values():
        for carga in cargas:
            if any(z.zona.nombre == nombre for z in carga.zonas):
                return carga.carro.numero
    raise AssertionError(nombre)


def _nivel(
    resultado: ResultadoBalanceo, nombre: str, observaciones: int = OBSERVACIONES_PARA_FIJAR
) -> NivelDeFijacion:
    zona = next(
        z.zona
        for cargas in resultado.cargas_por_municipio.values()
        for c in cargas
        for z in c.zonas
        if z.zona.nombre == nombre
    )
    return resultado.nivel_de_fijacion(zona, observaciones)


class TestLosTresCasosDeFrecuencia:
    def test_frecuencia_cero_es_fija_siempre(self) -> None:
        resultado = _repartir(0)

        assert _nivel(resultado, "(TUNJA): UNICA") is NivelDeFijacion.FIJA
        assert _nivel(resultado, "(TUNJA): UNICA", observaciones=10) is NivelDeFijacion.FIJA

    def test_vista_una_vez_es_sugerida_con_el_default(self) -> None:
        resultado = _repartir(1)

        assert OBSERVACIONES_PARA_FIJAR == 2
        assert _nivel(resultado, "(TUNJA): UNICA") is NivelDeFijacion.SUGERIDA
        assert _carro_de(resultado, "(TUNJA): UNICA") == "18"  # el reparto no cambia

    def test_vista_dos_veces_es_fija_con_el_default(self) -> None:
        assert _nivel(_repartir(2), "(TUNJA): UNICA") is NivelDeFijacion.FIJA


class TestElParametro:
    def test_con_uno_vuelve_el_comportamiento_anterior(self) -> None:
        assert _nivel(_repartir(1), "(TUNJA): UNICA", observaciones=1) is NivelDeFijacion.FIJA

    def test_con_tres_dos_observaciones_siguen_siendo_sugerencia(self) -> None:
        resultado = _repartir(2)

        assert _nivel(resultado, "(TUNJA): UNICA", observaciones=3) is NivelDeFijacion.SUGERIDA
        assert _nivel(_repartir(3), "(TUNJA): UNICA", observaciones=3) is NivelDeFijacion.FIJA


class TestLoQueNoCambia:
    def test_una_zona_con_dos_rutas_es_libre(self) -> None:
        assert _nivel(_repartir(1), "(TUNJA): DOBLE") is NivelDeFijacion.LIBRE

    def test_una_especial_sin_marcas_es_libre_y_con_una_marca_restringida(self) -> None:
        assert _nivel(_repartir(1), "(TUNJA): ESPECIAL") is NivelDeFijacion.LIBRE
        marcada = _repartir(1, {"20": {"(TUNJA): ESPECIAL"}})
        assert _nivel(marcada, "(TUNJA): ESPECIAL") is NivelDeFijacion.RESTRINGIDA_POR_MARCA

    def test_el_lado_de_chiquinquira_es_una_restriccion_y_no_una_fijacion(self) -> None:
        zona = _zona("(CHIQUINQUIRA): CHIQUIN SUR 1")
        carros = {"CHIQUINQUIRA": [Carro(numero="1"), Carro(numero="3")]}
        resultado = Balanceador().balancear([zona], carros, None, SIN_MEJORA, {"1": {zona.zona.nombre}})

        assert resultado.nivel_de_fijacion(zona.zona) is NivelDeFijacion.RESTRINGIDA_POR_LADO
        assert resultado.nivel_de_fijacion(zona.zona).inmovible

    def test_sin_repertorio_todo_es_libre(self) -> None:
        zonas = [_zona("(TUNJA): UNICA")]
        resultado = Balanceador().balancear(zonas, _CARROS, None, SIN_MEJORA, {})

        assert _nivel(resultado, "(TUNJA): UNICA") is NivelDeFijacion.LIBRE


class TestMoverUnaSugerida:
    def test_se_mueve_a_una_ruta_del_municipio_que_no_la_tiene_en_el_repertorio(self) -> None:
        resultado = _repartir(1)

        AjustadorDeAsignacion().mover(resultado, "(TUNJA): UNICA", "20")

        assert _carro_de(resultado, "(TUNJA): UNICA") == "20"

    def test_no_se_mueve_a_otro_municipio(self) -> None:
        with pytest.raises(MovimientoInvalido, match="se vio una sola vez"):
            AjustadorDeAsignacion().mover(_repartir(1), "(TUNJA): UNICA", "5")

    def test_una_fija_sigue_sin_poder_moverse_fuera_del_repertorio(self) -> None:
        with pytest.raises(MovimientoInvalido, match="no tiene permitida"):
            AjustadorDeAsignacion().mover(_repartir(2), "(TUNJA): UNICA", "20")

    def test_con_el_parametro_en_uno_la_vista_una_vez_tampoco_se_mueve(self) -> None:
        with pytest.raises(MovimientoInvalido, match="no tiene permitida"):
            AjustadorDeAsignacion().mover(_repartir(1), "(TUNJA): UNICA", "20", observaciones_para_fijar=1)
