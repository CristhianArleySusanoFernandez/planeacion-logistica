"""Lógica pura de la pantalla de la maestra de clientes: filtros, paginación y
traducción de una fila editada a un ``Cliente``.

Sin Streamlit a propósito, para poder probarla con pytest.

Son ~9.000 clientes, así que la pantalla nunca los muestra todos: pide un filtro
antes de listar y después pagina. El filtrado se hace acá en Python y no en la
consulta porque la búsqueda tiene que ignorar acentos (Rudy escribe "bogota" y la
maestra dice "BOGOTÁ") y PostgREST no sabe hacer eso sin ``unaccent``, que
implicaría tocar el esquema. La lista completa se lee una sola vez y queda
cacheada en la sesión — es la misma lectura que la planeación ya hace en cada
corrida para armar el resolutor de zonas, así que no agrega costo nuevo.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from planeacion.application.puertos.salida.repositorios import RepositorioClientes
from planeacion.domain.errores import ZonaInvalida
from planeacion.domain.modelo import Cliente, Zona
from planeacion.infraestructura.adaptadores.entrada.web.tablas import Fila, normalizar

TODOS = "Todos"
SIN_ZONA = "⚠ sin zona"

TAMANO_PAGINA = 50


@dataclass(frozen=True)
class FiltroClientes:
    """Los filtros combinables de la pantalla."""

    texto: str = ""
    zona: str = TODOS
    municipio: str = TODOS
    incluir_inactivos: bool = False

    @property
    def hay_criterio(self) -> bool:
        """¿Alcanza para listar? Sin esto la pantalla volcaría los 9.000 clientes.

        ``incluir_inactivos`` no cuenta: es un modificador de los demás filtros,
        no un criterio de búsqueda por sí solo.
        """
        return bool(self.texto.strip()) or self.zona != TODOS or self.municipio != TODOS


def _municipio_de(cliente: Cliente) -> str | None:
    return cliente.zona.municipio.nombre if cliente.zona else None


def filtrar_clientes(clientes: Sequence[Cliente], filtro: FiltroClientes) -> list[Cliente]:
    """Los clientes que pasan los cuatro filtros, ordenados por código.

    La búsqueda de texto es parcial y sin acentos sobre código, razón social y
    nombre de zona: son las tres formas en que Rudy busca a un cliente.
    """
    encontrados = list(clientes)
    if not filtro.incluir_inactivos:
        encontrados = [c for c in encontrados if c.activo]
    if filtro.zona == SIN_ZONA:
        encontrados = [c for c in encontrados if c.zona is None]
    elif filtro.zona != TODOS:
        encontrados = [c for c in encontrados if c.zona is not None and c.zona.nombre == filtro.zona]
    if filtro.municipio != TODOS:
        encontrados = [c for c in encontrados if _municipio_de(c) == filtro.municipio]

    clave = normalizar(filtro.texto)
    if clave:
        encontrados = [c for c in encontrados if clave in _texto_buscable(c)]
    return sorted(encontrados, key=lambda c: c.codigo)


def _texto_buscable(cliente: Cliente) -> str:
    partes = [cliente.codigo, cliente.razon_social or "", cliente.zona.nombre if cliente.zona else ""]
    return normalizar(" ".join(partes))


def total_paginas(cantidad: int, tamano: int = TAMANO_PAGINA) -> int:
    """Cuántas páginas ocupan ``cantidad`` resultados (mínimo 1, aun sin resultados)."""
    return max(1, -(-cantidad // tamano))


def pagina(clientes: Sequence[Cliente], numero: int, tamano: int = TAMANO_PAGINA) -> list[Cliente]:
    """El bloque ``numero`` (1-based) de resultados. Un número fuera de rango da []."""
    inicio = (numero - 1) * tamano
    if inicio < 0:
        return []
    return list(clientes[inicio : inicio + tamano])


def a_fila(cliente: Cliente) -> Fila:
    """Cliente → la fila que muestra el editor."""
    return {
        "codigo": cliente.codigo,
        "razon_social": cliente.razon_social or "",
        "documento": cliente.documento or "",
        "ciudad": cliente.ciudad or "",
        "barrio": cliente.barrio or "",
        "direccion": cliente.direccion or "",
        "zona": cliente.zona.nombre if cliente.zona else "",
        "activo": cliente.activo,
    }


def cliente_editado(original: Cliente, fila: Fila, zonas: Mapping[str, Zona]) -> Cliente:
    """Fila editada → el ``Cliente`` a guardar, conservando lo que no se edita.

    ``dia_visita`` no está en la pantalla y se arrastra del original: el guardado
    es un upsert de la fila entera, así que omitirlo lo borraría de la base.
    Dejar la zona en blanco sí es intencional y deja al cliente sin zona (vuelve
    a caer como no resuelto en el paso 2), que es como se corrige una mal puesta.
    """
    return Cliente(
        codigo=original.codigo,
        razon_social=_o_nada(fila.get("razon_social")),
        documento=_o_nada(fila.get("documento")),
        ciudad=_o_nada(fila.get("ciudad")),
        barrio=_o_nada(fila.get("barrio")),
        direccion=_o_nada(fila.get("direccion")),
        zona=_zona_de(fila.get("zona"), zonas),
        dia_visita=original.dia_visita,
        activo=bool(fila.get("activo", True)),
    )


def _o_nada(valor: object) -> str | None:
    texto = str(valor).strip() if valor is not None else ""
    return texto or None


def _zona_de(valor: object, zonas: Mapping[str, Zona]) -> Zona | None:
    """El nombre elegido → la Zona del catálogo, tal cual está en la base.

    Se busca en vez de construirla con ``crear_zona`` porque esa función colapsa
    los espacios y los nombres reales traen dobles ("(TUNJA):  NIEVES"): guardar
    la versión normalizada apuntaría a una zona que no existe.
    """
    nombre = _o_nada(valor)
    if nombre is None:
        return None
    zona = zonas.get(nombre)
    if zona is None:
        raise ZonaInvalida(f"la zona {nombre!r} no está en el catálogo")
    return zona


def clientes_modificados(
    originales: Sequence[Cliente], filas: Sequence[Fila], zonas: Mapping[str, Zona]
) -> list[Cliente]:
    """Solo los clientes cuya fila realmente cambió.

    El editor devuelve la página entera en cada rerun; sin este filtro cada
    guardado escribiría 50 clientes para corregir uno solo.
    """
    por_codigo = {cliente.codigo: cliente for cliente in originales}
    cambiados = []
    for fila in filas:
        original = por_codigo.get(str(fila.get("codigo", "")))
        if original is None:
            continue
        editado = cliente_editado(original, fila, zonas)
        if editado != original:
            cambiados.append(editado)
    return cambiados


@dataclass(frozen=True)
class ResultadoGuardado:
    """Qué se pudo guardar y qué no. Un fallo no frena a los demás clientes."""

    guardados: int
    errores: tuple[str, ...]


def aplicar_cambios(
    repositorio: RepositorioClientes,
    originales: Sequence[Cliente],
    filas: Sequence[Fila],
    zonas: Mapping[str, Zona],
) -> ResultadoGuardado:
    """Persiste solo los clientes cuya fila cambió.

    Se guarda cliente por cliente (no en lote) para que el error de uno —una zona
    que ya no existe, un problema de red— no tire abajo las correcciones buenas
    de la misma página; el cliente que falló se reporta y queda sin cambiar.
    """
    errores: list[str] = []
    guardados = 0
    for cliente in clientes_modificados(originales, filas, zonas):
        try:
            repositorio.guardar_cliente(cliente)
            guardados += 1
        except Exception as error:  # error de red o de datos: se reporta sin frenar el resto
            errores.append(f"No se pudo guardar el cliente {cliente.codigo}: {error}")
    return ResultadoGuardado(guardados, tuple(errores))
