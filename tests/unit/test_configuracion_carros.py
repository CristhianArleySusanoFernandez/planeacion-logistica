"""La pestaña Carros ya no muestra ``es_externo`` ni ``costo_diario``.

Ningún servicio los lee: son datos de referencia para la recomendación de carro
externo, que todavía no existe. Lo que SÍ hay que garantizar es que guardar una
fila desde la pestaña no los borre: la fila del editor no los trae, así que se
copian del carro ya guardado.
"""

from decimal import Decimal

from planeacion.domain.modelo import Carro, Municipio
from planeacion.infraestructura.adaptadores.entrada.web.configuracion import _carro_desde_fila

_FILA = {
    "numero": "16",
    "conductor": "CARLOS 1",
    "conductor_clave": None,
    "placa": "ABC123",
    "auxiliar": None,
    "municipio": "TUNJA",
    "municipio_real": None,
    "lado_chiquinquira": None,
    "activo": True,
}


class TestEditarUnaFilaPreservaLosDatosDeReferencia:
    def test_el_carro_externo_sigue_externo_y_con_su_costo(self) -> None:
        actual = Carro(numero="16", conductor="CARLOS 1", es_externo=True, costo_diario=Decimal("160000"))

        carro = _carro_desde_fila(_FILA, actual)

        assert carro.es_externo is True
        assert carro.costo_diario == Decimal("160000")
        assert carro.placa == "ABC123" and carro.municipio == Municipio("TUNJA")

    def test_una_fila_con_los_campos_viejos_los_ignora(self) -> None:
        """Si un estado viejo del editor todavía trae las columnas, mandan los datos
        guardados, no la fila."""
        actual = Carro(numero="16", es_externo=True, costo_diario=Decimal("160000"))
        fila = {**_FILA, "es_externo": False, "costo_diario": 0.0}

        carro = _carro_desde_fila(fila, actual)

        assert carro.es_externo is True and carro.costo_diario == Decimal("160000")

    def test_una_ruta_nueva_nace_con_los_defaults(self) -> None:
        carro = _carro_desde_fila({**_FILA, "numero": "24"}, None)

        assert carro.es_externo is False and carro.costo_diario == Decimal("0")

    def test_la_clave_de_conductor_se_sigue_deduciendo(self) -> None:
        assert _carro_desde_fila(_FILA, None).conductor_clave == "CARLOS"
