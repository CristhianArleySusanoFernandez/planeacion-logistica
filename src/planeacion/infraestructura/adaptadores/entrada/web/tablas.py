"""Helpers puros de las tablas editables de Configuración: filtro de texto y
diff de filas (nuevas / editadas / eliminadas). Sin Streamlit a propósito, para
poder probarlos con pytest.
"""

import unicodedata
from dataclasses import dataclass
from typing import Any

Fila = dict[str, Any]


def normalizar(texto: str) -> str:
    """Texto → forma comparable: minúsculas, sin acentos, espacios colapsados.

    Vive acá y no en cada pantalla porque toda búsqueda de Configuración compara
    así: lo que Rudy escribe casi nunca lleva las tildes que sí trae la maestra.
    """
    sin_acentos = "".join(
        caracter for caracter in unicodedata.normalize("NFD", texto) if not unicodedata.combining(caracter)
    )
    return " ".join(sin_acentos.lower().split())


def filtrar_filas(filas: list[Fila], texto: str) -> list[Fila]:
    """Coincidencia parcial case-insensitive sobre cualquier columna de texto."""
    clave = texto.strip().lower()
    if not clave:
        return list(filas)
    return [
        fila
        for fila in filas
        if any(isinstance(valor, str) and clave in valor.lower() for valor in fila.values())
    ]


@dataclass(frozen=True)
class DiffFilas:
    """Qué cambió en el editor respecto de las filas visibles originales."""

    nuevas: list[Fila]
    editadas: list[Fila]
    eliminadas: list[str]  # valores de la columna clave
    invalidas: list[Fila]  # filas con datos pero sin la columna clave


def calcular_diff(originales: list[Fila], editadas: list[Fila], clave: str) -> DiffFilas:
    """Diff por llave estable (numero / nombre / cliente_codigo).

    IMPORTANTE: ``originales`` deben ser las filas VISIBLES (tras el filtro de
    texto): una fila oculta por el filtro nunca cuenta como eliminada. Cambiarle
    la llave a una fila equivale a crear una nueva y eliminar la vieja.
    """
    previas = {str(fila[clave]): fila for fila in originales}
    actuales: dict[str, Fila] = {}
    invalidas: list[Fila] = []
    for fila in editadas:
        valor = fila.get(clave)
        llave = str(valor).strip() if valor is not None else ""
        if not llave:
            # Fila del editor sin llave: inválida si trae algún dato, si no se ignora.
            tiene_datos = any(v not in (None, "", False) for campo, v in fila.items() if campo != clave)
            if tiene_datos:
                invalidas.append(fila)
            continue
        actuales[llave] = fila
    return DiffFilas(
        nuevas=[fila for llave, fila in actuales.items() if llave not in previas],
        editadas=[fila for llave, fila in actuales.items() if llave in previas and fila != previas[llave]],
        eliminadas=[llave for llave in previas if llave not in actuales],
        invalidas=invalidas,
    )
