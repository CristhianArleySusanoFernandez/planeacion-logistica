"""Lógica pura de la matriz de repertorios (zonas × carros) de Configuración:
filtros, contadores, frecuencias, copia entre días y traducción/persistencia de
los cambios de casillas. Sin Streamlit a propósito, para poder probarla con pytest.

La matriz muestra **un día a la vez**: el repertorio depende del día de la semana
(ver migración 003), así que todo lo de acá trabaja sobre el repertorio de un día
ya resuelto por quien llama.
"""

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass

from planeacion.application.puertos.salida.repositorios import ParRepertorio, RepositorioCarroZonas
from planeacion.domain.modelo import Carro, Zona
from planeacion.infraestructura.adaptadores.entrada.web.tablas import normalizar

TODOS = "Todos"

# numero de carro → nombres de zona permitidos (lo que da obtener_por_dia()).
Repertorio = Mapping[str, set[str]]

# (numero de carro, nombre de zona) → veces observado ese día en el histórico.
FrecuenciasDelDia = Mapping[tuple[str, str], int]

# Un par visto UNA sola vez suele ser un reemplazo puntual (el conductor de
# siempre faltó ese día), no una regla del negocio. Se marca para que la usuaria
# lo revise; la decisión de conservarlo o no es de ella, no del programa.
FRECUENCIA_SOSPECHOSA = 1


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


def aplicar_cambios(
    repositorio: RepositorioCarroZonas, cambios: Sequence[CambioCelda], dia_semana: str
) -> list[str]:
    """Persiste cada cambio del día en pantalla (marcado → asignar, desmarcado →
    quitar) y devuelve los mensajes de error de los que fallaron; los demás quedan
    guardados. La casilla de un cambio fallido se revierte en la UI al recargar la
    matriz desde la base."""
    errores: list[str] = []
    for cambio in cambios:
        try:
            if cambio.marcado:
                repositorio.asignar(cambio.numero_carro, cambio.nombre_zona, dia_semana)
            else:
                repositorio.quitar(cambio.numero_carro, cambio.nombre_zona, dia_semana)
        except Exception as error:  # error de red o de datos: se reporta sin frenar el resto
            accion = "asignar" if cambio.marcado else "quitar"
            errores.append(
                f"No se pudo {accion} {cambio.nombre_zona} al carro {cambio.numero_carro} "
                f"({dia_semana}): {error}"
            )
    return errores


def frecuencias_del_dia(frecuencias: Mapping[ParRepertorio, int], dia_semana: str) -> FrecuenciasDelDia:
    """Las frecuencias de un solo día, con la clave que usa la matriz."""
    return {
        (par.numero_carro, par.nombre_zona): veces
        for par, veces in frecuencias.items()
        if par.dia_semana == dia_semana
    }


def resumen_de_frecuencias(nombre_zona: str, repertorio: Repertorio, frecuencias: FrecuenciasDelDia) -> str:
    """La celda de resumen de una fila: "13×8 · 12×1", con ⚠ si algún par se vio
    una sola vez.

    Existe como columna aparte porque una casilla de ``st.data_editor`` es un
    checkbox y no puede llevar el número al lado; el resumen por fila deja la
    frecuencia junto a los checks de esa zona, que es donde hace falta leerla.
    """
    marcados = sorted(
        (numero for numero, zonas in repertorio.items() if nombre_zona in zonas),
        key=lambda n: (len(n), n),
    )
    if not marcados:
        return ""
    partes = [f"{numero}×{frecuencias.get((numero, nombre_zona), 0)}" for numero in marcados]
    hay_sospechoso = any(
        frecuencias.get((numero, nombre_zona), 0) == FRECUENCIA_SOSPECHOSA for numero in marcados
    )
    return ("⚠ " if hay_sospechoso else "") + " · ".join(partes)


def pares_sospechosos(
    zonas: Sequence[Zona], repertorio: Repertorio, frecuencias: FrecuenciasDelDia
) -> list[tuple[str, str]]:
    """(zona, carro) de los pares vistos una sola vez, ordenados por zona.

    Son los candidatos a borrar: la usuaria los revisa y decide si eran una regla
    o el reemplazo de un día suelto.
    """
    sospechosos = [
        (zona.nombre, numero)
        for zona in zonas
        for numero, permitidas in repertorio.items()
        if zona.nombre in permitidas and frecuencias.get((numero, zona.nombre), 0) == FRECUENCIA_SOSPECHOSA
    ]
    return sorted(sospechosos, key=lambda par: (par[0], len(par[1]), par[1]))


def cambios_para_copiar(origen: Repertorio, destino: Repertorio) -> list[CambioCelda]:
    """Los cambios que dejan a ``destino`` igual que ``origen``.

    Copiar un día sobre otro es la forma rápida de configurar: la mayoría de los
    días se parecen entre sí, así que se copia y después se ajustan las pocas
    diferencias. Devuelve altas y BAJAS: el resultado es el día de origen tal cual,
    no la unión de los dos (si no, un día nunca podría quedar con menos pares que
    otro y la copia sería irreversible).
    """
    numeros = set(origen) | set(destino)
    cambios: list[CambioCelda] = []
    for numero in sorted(numeros, key=lambda n: (len(n), n)):
        permitidas_origen = set(origen.get(numero, set()))
        permitidas_destino = set(destino.get(numero, set()))
        for zona in sorted(permitidas_origen - permitidas_destino):
            cambios.append(CambioCelda(numero, zona, True))
        for zona in sorted(permitidas_destino - permitidas_origen):
            cambios.append(CambioCelda(numero, zona, False))
    return cambios
