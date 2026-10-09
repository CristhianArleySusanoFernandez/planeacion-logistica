"""Pruebas del cache de lecturas de la interfaz.

Lo que importa no es que el cache exista, es que **se invalide cuando se
escribe**: el pedido explícito fue que cambiar la zona de un cliente se vea al
instante. Un cache que no se invalida es peor que no tenerlo.

El contexto: Streamlit reejecuta el script en cada interacción y `st.tabs`
dibuja las siete pestañas en cada pasada, así que un clic en Configuración
disparaba 13 lecturas, entre ellas la maestra completa.
"""

from collections import Counter
from decimal import Decimal
from typing import Any, cast

import pytest

from planeacion.config.contenedor import Contenedor
from planeacion.domain.modelo import Cliente
from planeacion.infraestructura.adaptadores.entrada.web import datos

_LLAMADAS: Counter[str] = Counter()


class _RepoFalso:
    """Cuenta cada lectura y devuelve algo con la forma correcta."""

    def __init__(self, nombre: str, valor: Any) -> None:
        self._nombre = nombre
        self._valor = valor

    def _contar(self) -> Any:
        _LLAMADAS[self._nombre] += 1
        return self._valor

    def listar(self) -> Any:
        return self._contar()

    def obtener(self) -> Any:
        return self._contar()

    def obtener_matriz(self) -> Any:
        return self._contar()

    def frecuencias(self) -> Any:
        return self._contar()


def _contenedor() -> Contenedor:
    campos = {
        "clientes": [Cliente(codigo="111")],
        "zonas": [],
        "municipios": [],
        "carros": [],
        "carro_zonas": {},
        "correcciones": [],
        "overrides": [],
        "planeaciones": None,
        "parametros": {"w_kilos": Decimal("0.5")},
    }
    return Contenedor(**{nombre: cast(Any, _RepoFalso(nombre, valor)) for nombre, valor in campos.items()})


@pytest.fixture(autouse=True)
def _cache_limpio() -> None:
    datos.invalidar_todo()
    _LLAMADAS.clear()


class TestCache:
    def test_la_segunda_lectura_no_vuelve_a_la_base(self) -> None:
        contenedor = _contenedor()

        datos.maestra(contenedor)
        datos.maestra(contenedor)
        datos.maestra(contenedor)

        assert _LLAMADAS["clientes"] == 1

    def test_cada_lectura_tiene_su_propio_cache(self) -> None:
        """Leer zonas no puede traer la maestra de arrastre ni al revés."""
        contenedor = _contenedor()

        datos.zonas(contenedor)
        datos.zonas(contenedor)

        assert _LLAMADAS["zonas"] == 1
        assert _LLAMADAS["clientes"] == 0


class TestInvalidacion:
    def test_guardar_un_cliente_hace_que_la_maestra_se_relea(self) -> None:
        """El caso concreto del pedido: cambiar la zona de un cliente se ve ya."""
        contenedor = _contenedor()
        datos.maestra(contenedor)

        datos.invalidar_clientes()
        datos.maestra(contenedor)

        assert _LLAMADAS["clientes"] == 2

    def test_tocar_zonas_tambien_invalida_la_matriz_y_la_maestra(self) -> None:
        """Las filas de la matriz SON las zonas, y la zona del cliente se guarda
        por nombre: si cambia el catálogo, las tres vistas quedaron viejas."""
        contenedor = _contenedor()
        datos.zonas(contenedor)
        datos.matriz_repertorio(contenedor)
        datos.maestra(contenedor)

        datos.invalidar_zonas()
        datos.zonas(contenedor)
        datos.matriz_repertorio(contenedor)
        datos.maestra(contenedor)

        assert _LLAMADAS["zonas"] == 2
        assert _LLAMADAS["carro_zonas"] == 2
        assert _LLAMADAS["clientes"] == 2

    def test_marcar_una_casilla_del_repertorio_no_tira_el_cache_de_la_maestra(self) -> None:
        """La razón de invalidar por entidad y no todo: la matriz escribe en CADA
        clic, y si eso volviera a traer los 9.200 clientes el arreglo no serviría."""
        contenedor = _contenedor()
        datos.maestra(contenedor)
        datos.matriz_repertorio(contenedor)

        datos.invalidar_repertorio()
        datos.maestra(contenedor)
        datos.matriz_repertorio(contenedor)

        assert _LLAMADAS["clientes"] == 1  # no se volvió a leer
        assert _LLAMADAS["carro_zonas"] == 2

    def test_la_flota_se_relea_al_guardar_un_carro_y_arrastra_la_matriz(self) -> None:
        """Las columnas de la matriz son los carros activos."""
        contenedor = _contenedor()
        datos.flota(contenedor)
        datos.matriz_repertorio(contenedor)

        datos.invalidar_flota()
        datos.flota(contenedor)
        datos.matriz_repertorio(contenedor)

        assert _LLAMADAS["carros"] == 2
        assert _LLAMADAS["carro_zonas"] == 2

    def test_los_parametros_se_releen_al_restaurarlos(self) -> None:
        contenedor = _contenedor()
        datos.parametros(contenedor)

        datos.invalidar_parametros()
        datos.parametros(contenedor)

        assert _LLAMADAS["parametros"] == 2

    def test_invalidar_todo_vacia_las_nueve_lecturas(self) -> None:
        contenedor = _contenedor()
        for lectura in (
            datos.maestra,
            datos.zonas,
            datos.municipios,
            datos.flota,
            datos.matriz_repertorio,
            datos.frecuencias,
            datos.correcciones,
            datos.overrides,
            datos.parametros,
        ):
            lectura(contenedor)
        leidas = sum(_LLAMADAS.values())

        datos.invalidar_todo()
        for lectura in (
            datos.maestra,
            datos.zonas,
            datos.municipios,
            datos.flota,
            datos.matriz_repertorio,
            datos.frecuencias,
            datos.correcciones,
            datos.overrides,
            datos.parametros,
        ):
            lectura(contenedor)

        assert sum(_LLAMADAS.values()) == leidas * 2
