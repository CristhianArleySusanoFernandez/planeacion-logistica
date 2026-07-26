"""Pruebas de la traducción fila ↔ modelo de los adaptadores Supabase (sin red)."""

from decimal import Decimal

from planeacion.domain.modelo import (
    Carro,
    Cliente,
    CorreccionUbicacion,
    Municipio,
    OverrideZona,
    ReglaChiquinquira,
    Zona,
)
from planeacion.infraestructura.adaptadores.salida.supabase import (
    repositorio_carros,
    repositorio_clientes,
    repositorio_correcciones,
    repositorio_overrides,
    repositorio_zonas,
)

_ZONA_PUENTE = Zona(nombre="(BARBOSA): BARBOSA-PUENTE", municipio=Municipio(nombre="BARBOSA"))


class TestTraduccionZonas:
    def test_a_fila_resuelve_municipio_y_regla(self) -> None:
        zona = Zona(
            nombre="(CHIQUINQUIRA): SUSA RUTA SUR 1",
            municipio=Municipio(nombre="CHIQUINQUIRA"),
            regla_chiquinquira=ReglaChiquinquira.SUR,
        )
        fila = repositorio_zonas.a_fila(zona, {"CHIQUINQUIRA": 7})
        assert fila == {
            "nombre": "(CHIQUINQUIRA): SUSA RUTA SUR 1",
            "municipio_id": 7,
            "regla_chiquinquira": "SUR",
            "activa": True,
        }

    def test_desde_fila_con_municipio_anidado(self) -> None:
        zona = repositorio_zonas.desde_fila(
            {
                "nombre": "(TUNJA): PATRIOTAS",
                "regla_chiquinquira": None,
                "activa": True,
                "municipios": {"nombre": "TUNJA"},
            }
        )
        assert zona == Zona(nombre="(TUNJA): PATRIOTAS", municipio=Municipio(nombre="TUNJA"))


class TestTraduccionCarros:
    def test_ida_y_vuelta(self) -> None:
        carro = Carro(
            numero="16",
            conductor="EXTERNO",
            placa="XYZ123",
            auxiliar="NO",
            municipio=Municipio(nombre="TUNJA"),
            es_externo=True,
            costo_diario=Decimal("160000"),
        )
        fila = repositorio_carros.a_fila(carro, {"TUNJA": 3})
        assert fila["municipio_id"] == 3
        assert fila["es_externo"] is True
        assert fila["costo_diario"] == "160000"

        reconstruido = repositorio_carros.desde_fila({**fila, "municipios": {"nombre": "TUNJA"}})
        assert reconstruido == carro

    def test_sin_municipio(self) -> None:
        fila = repositorio_carros.a_fila(Carro(numero="108"), {"TUNJA": 3})
        assert fila["municipio_id"] is None


class TestTraduccionClientes:
    def test_a_fila_resuelve_zona(self) -> None:
        cliente = Cliente(codigo="200001941691", direccion="CR 3 4 61", zona=_ZONA_PUENTE)
        fila = repositorio_clientes.a_fila(cliente, {_ZONA_PUENTE.nombre: 42})
        assert fila["codigo"] == "200001941691"
        assert fila["zona_id"] == 42

    def test_a_fila_sin_zona(self) -> None:
        fila = repositorio_clientes.a_fila(Cliente(codigo="X"), {})
        assert fila["zona_id"] is None

    def test_desde_fila_con_zona_anidada(self) -> None:
        cliente = repositorio_clientes.desde_fila(
            {
                "codigo": "000373476",
                "direccion": "CL 67A 8A 06",
                "barrio": "PRADOS DEL NORTE",
                "ciudad": "TUNJA",
                "documento": None,
                "razon_social": None,
                "dia_visita": None,
                "activo": True,
                "zonas": {
                    "nombre": "(BARBOSA): BARBOSA-PUENTE",
                    "regla_chiquinquira": None,
                    "activa": True,
                    "municipios": {"nombre": "BARBOSA"},
                },
            }
        )
        assert cliente.codigo == "000373476"  # conserva ceros a la izquierda
        assert cliente.zona == _ZONA_PUENTE


class TestTraduccionCorreccionesYOverrides:
    def test_correccion_ida_y_vuelta(self) -> None:
        correccion = CorreccionUbicacion(
            cliente_codigo="200002023517", ciudad_real="combita", barrio_real=None
        )
        assert repositorio_correcciones.desde_fila(repositorio_correcciones.a_fila(correccion)) == correccion

    def test_override_a_fila_resuelve_zona(self) -> None:
        override = OverrideZona(cliente_codigo="000371446", zona_nombre="(BARBOSA): BARBOSA-PUENTE")
        fila = repositorio_overrides.a_fila(override, {"(BARBOSA): BARBOSA-PUENTE": 42})
        assert fila == {"cliente_codigo": "000371446", "zona_id": 42}

    def test_override_desde_fila_anidada(self) -> None:
        override = repositorio_overrides.desde_fila(
            {"cliente_codigo": "000371446", "zonas": {"nombre": "(BARBOSA): BARBOSA-PUENTE"}}
        )
        assert override.zona_nombre == "(BARBOSA): BARBOSA-PUENTE"
