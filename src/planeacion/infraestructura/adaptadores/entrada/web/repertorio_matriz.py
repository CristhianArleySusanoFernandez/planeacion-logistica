"""Lógica pura de la matriz de repertorios (zonas × carros) de Configuración:
filtros, contadores y traducción/persistencia de los cambios de casillas.
Sin Streamlit a propósito, para poder probarla con pytest.
"""

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass

from planeacion.application.puertos.salida.repositorios import RepositorioCarroZonas
from planeacion.domain.modelo import Carro, Zona
from planeacion.infraestructura.adaptadores.entrada.web.tablas import normalizar

TODOS = "Todos"

# numero de carro → nombres de zona permitidos (lo que da obtener_todos()).
Repertorio = Mapping[str, set[str]]


@dataclass(frozen=True)
class FiltroMatriz:
    """Los tres filtros combinables de la matriz."""

    municipio: str = TODOS
    solo_sin_carro: bool = False
    texto: str = ""


@dataclass(frozen=True)
class CambioCelda:
    """Una casilla que cambió: (carro, zona) marcado o desmarcado."""

    numero_carro: str
    nombre_zona: str
    marcado: bool


def contar_carros_de_zona(nombre_zona: str, repertorio: Repertorio) -> int:
    """Cuántos carros tienen la zona en su repertorio (0 = huérfana)."""
    return sum(1 for zonas in repertorio.values() if nombre_zona in zonas)


def contar_sin_carro(zonas: Sequence[Zona], repertorio: Repertorio) -> tuple[int, int]:
    """(zonas sin ningún carro, total de zonas) — el contador de progreso."""
    sin_carro = sum(1 for zona in zonas if contar_carros_de_zona(zona.nombre, repertorio) == 0)
    return sin_carro, len(zonas)


def zonas_visibles(zonas: Sequence[Zona], repertorio: Repertorio, filtro: FiltroMatriz) -> list[Zona]:
    """Las filas de la matriz: municipio + solo-sin-carro + búsqueda (sin acentos),
    ordenadas alfabéticamente por nombre dentro del municipio."""
    visibles = [z for z in zonas if filtro.municipio in (TODOS, z.municipio.nombre)]
    if filtro.solo_sin_carro:
        visibles = [z for z in visibles if contar_carros_de_zona(z.nombre, repertorio) == 0]
    clave = normalizar(filtro.texto)
    if clave:
        visibles = [z for z in visibles if clave in normalizar(z.nombre)]
    return sorted(visibles, key=lambda z: (z.municipio.nombre, z.nombre))


def _orden_carro(carro: Carro) -> tuple[int, str]:
    return (len(carro.numero), carro.numero)


def carros_visibles(
    carros: Sequence[Carro],
    zonas_filas: Sequence[Zona],
    repertorio: Repertorio,
    municipio: str,
) -> list[Carro]:
    """Las columnas de la matriz: los carros activos del municipio filtrado más los
    de otros municipios que ya atienden alguna zona visible (viajeras cruzadas,
    ej. RAQUIRA en el carro 2 de Chiquinquirá)."""
    activos = [c for c in carros if c.activo]
    if municipio == TODOS:
        return sorted(activos, key=_orden_carro)
    propios = [c for c in activos if c.municipio is not None and c.municipio.nombre == municipio]
    numeros_propios = {c.numero for c in propios}
    nombres_filas = {z.nombre for z in zonas_filas}
    cruzados = [
        c
        for c in activos
        if c.numero not in numeros_propios and repertorio.get(c.numero, set()) & nombres_filas
    ]
    return sorted(propios, key=_orden_carro) + sorted(cruzados, key=_orden_carro)


def cambios_desde_edicion(
    filas_editadas: Mapping[int, Mapping[str, object]],
    orden_zonas: Sequence[str],
    numeros_carros: Collection[str],
) -> list[CambioCelda]:
    """Traduce el ``edited_rows`` del data_editor ({índice de fila: {columna: valor}})
    a cambios de celda. Solo cuentan las columnas de carro con valor booleano; el
    resto (nombre de zona, contador) se ignora."""
    cambios: list[CambioCelda] = []
    for indice, columnas in filas_editadas.items():
        if not 0 <= indice < len(orden_zonas):
            continue  # una fila que ya no existe en la vista actual
        for columna, valor in columnas.items():
            if columna in numeros_carros and isinstance(valor, bool):
                cambios.append(CambioCelda(columna, orden_zonas[indice], valor))
    return cambios


def aplicar_cambios(repositorio: RepositorioCarroZonas, cambios: Sequence[CambioCelda]) -> list[str]:
    """Persiste cada cambio (marcado → asignar, desmarcado → quitar) y devuelve los
    mensajes de error de los que fallaron; los demás quedan guardados. La casilla
    de un cambio fallido se revierte en la UI al recargar la matriz desde la base."""
    errores: list[str] = []
    for cambio in cambios:
        try:
            if cambio.marcado:
                repositorio.asignar(cambio.numero_carro, cambio.nombre_zona)
            else:
                repositorio.quitar(cambio.numero_carro, cambio.nombre_zona)
        except Exception as error:  # error de red o de datos: se reporta sin frenar el resto
            accion = "asignar" if cambio.marcado else "quitar"
            errores.append(
                f"No se pudo {accion} {cambio.nombre_zona} al carro {cambio.numero_carro}: {error}"
            )
    return errores
