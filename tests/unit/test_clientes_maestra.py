"""Pruebas de la lógica pura de la pantalla de la maestra de clientes."""

import pytest

from planeacion.domain.errores import ZonaInvalida
from planeacion.domain.modelo import Cliente, Municipio, Zona
from planeacion.infraestructura.adaptadores.entrada.web.clientes_maestra import (
    SIN_ZONA,
    TODOS,
    FiltroClientes,
    ResultadoGuardado,
    a_fila,
    aplicar_cambios,
    cliente_editado,
    clientes_modificados,
    filtrar_clientes,
    pagina,
    total_paginas,
)


def _zona(nombre: str, municipio: str) -> Zona:
    return Zona(nombre=nombre, municipio=Municipio(nombre=municipio))


# Los nombres reales de la base traen espacios dobles; se conservan tal cual.
_TUNJA = _zona("(TUNJA):  NIEVES", "TUNJA")
_BARBOSA = _zona("(BARBOSA):  CITE", "BARBOSA")
_CATALOGO = {zona.nombre: zona for zona in (_TUNJA, _BARBOSA)}


def _cliente(
    codigo: str,
    razon_social: str | None = None,
    zona: Zona | None = _TUNJA,
    activo: bool = True,
) -> Cliente:
    return Cliente(
        codigo=codigo,
        razon_social=razon_social,
        zona=zona,
        activo=activo,
        ciudad="15001 - TUNJA",
        barrio="CENTRO",
        direccion="CALLE 1",
        documento="900123",
    )


_CLIENTES = [
    _cliente("8043", "TIENDA DOÑA MARÍA"),
    _cliente("120", "SUPERMERCADO EL SOL", zona=_BARBOSA),
    _cliente("77", "PANADERÍA BOGOTÁ", zona=None),
    _cliente("9001", "NEGOCIO CERRADO", activo=False),
]


class TestFiltrar:
    def test_sin_criterio_no_se_lista_nada(self) -> None:
        """Los ~9.000 clientes no se vuelcan en pantalla: hace falta filtrar."""
        assert FiltroClientes().hay_criterio is False
        assert FiltroClientes(incluir_inactivos=True).hay_criterio is False
        assert FiltroClientes(texto="doña").hay_criterio is True
        assert FiltroClientes(zona="(TUNJA):  NIEVES").hay_criterio is True

    def test_busca_por_razon_social_ignorando_acentos(self) -> None:
        """Rudy escribe sin tildes y la maestra las trae."""
        encontrados = filtrar_clientes(_CLIENTES, FiltroClientes(texto="panaderia bogota"))

        assert [c.codigo for c in encontrados] == ["77"]

    def test_busca_por_codigo_y_por_zona(self) -> None:
        por_codigo = filtrar_clientes(_CLIENTES, FiltroClientes(texto="8043"))
        por_zona = filtrar_clientes(_CLIENTES, FiltroClientes(texto="cite"))

        assert [c.codigo for c in por_codigo] == ["8043"]
        assert [c.codigo for c in por_zona] == ["120"]

    def test_los_inactivos_quedan_fuera_salvo_que_se_pidan(self) -> None:
        """Desactivar no borra: el cliente sigue ahí, pero deja de estorbar."""
        filtro = FiltroClientes(texto="negocio")

        assert filtrar_clientes(_CLIENTES, filtro) == []
        encontrados = filtrar_clientes(_CLIENTES, FiltroClientes(texto="negocio", incluir_inactivos=True))
        assert [c.codigo for c in encontrados] == ["9001"]

    def test_filtro_por_zona_y_por_municipio(self) -> None:
        por_zona = filtrar_clientes(_CLIENTES, FiltroClientes(zona="(BARBOSA):  CITE"))
        por_municipio = filtrar_clientes(_CLIENTES, FiltroClientes(municipio="TUNJA"))

        assert [c.codigo for c in por_zona] == ["120"]
        assert [c.codigo for c in por_municipio] == ["8043"]

    def test_los_sin_zona_se_pueden_aislar(self) -> None:
        """Son los que más importa corregir: caen como no resueltos en el paso 2."""
        encontrados = filtrar_clientes(_CLIENTES, FiltroClientes(zona=SIN_ZONA))

        assert [c.codigo for c in encontrados] == ["77"]

    def test_el_municipio_no_arrastra_a_los_clientes_sin_zona(self) -> None:
        """Sin zona no hay municipio: filtrar por uno no puede devolverlos."""
        encontrados = filtrar_clientes([_cliente("77", zona=None)], FiltroClientes(municipio="TUNJA"))

        assert encontrados == []

    def test_el_resultado_sale_ordenado_por_codigo(self) -> None:
        encontrados = filtrar_clientes(_CLIENTES, FiltroClientes(municipio=TODOS, texto="a"))

        assert [c.codigo for c in encontrados] == sorted(c.codigo for c in encontrados)


class TestPaginacion:
    def test_parte_los_resultados_en_bloques(self) -> None:
        clientes = [_cliente(str(numero)) for numero in range(1, 8)]

        assert [c.codigo for c in pagina(clientes, 1, tamano=3)] == ["1", "2", "3"]
        assert [c.codigo for c in pagina(clientes, 3, tamano=3)] == ["7"]

    def test_una_pagina_fuera_de_rango_no_revienta(self) -> None:
        assert pagina(_CLIENTES, 99) == []
        assert pagina(_CLIENTES, 0, tamano=10) == []

    def test_siempre_hay_al_menos_una_pagina(self) -> None:
        assert total_paginas(0) == 1
        assert total_paginas(7, tamano=3) == 3
        assert total_paginas(6, tamano=3) == 2


class TestEdicion:
    def test_corregir_la_zona_es_lo_que_mas_importa(self) -> None:
        original = _cliente("8043")
        fila = a_fila(original) | {"zona": "(BARBOSA):  CITE"}

        editado = cliente_editado(original, fila, _CATALOGO)

        assert editado.zona == _BARBOSA
        assert editado.codigo == "8043"

    def test_dejar_la_zona_en_blanco_deja_al_cliente_sin_zona(self) -> None:
        original = _cliente("8043")

        editado = cliente_editado(original, a_fila(original) | {"zona": ""}, _CATALOGO)

        assert editado.zona is None

    def test_desactivar_conserva_el_resto_de_los_datos(self) -> None:
        original = _cliente("8043", "TIENDA DOÑA MARÍA")

        editado = cliente_editado(original, a_fila(original) | {"activo": False}, _CATALOGO)

        assert editado.activo is False
        assert (editado.razon_social, editado.ciudad, editado.zona) == (
            original.razon_social,
            original.ciudad,
            original.zona,
        )

    def test_el_dia_de_visita_no_se_pierde_aunque_no_este_en_la_pantalla(self) -> None:
        """El guardado es un upsert de la fila entera: omitir el campo lo borraría."""
        original = Cliente(codigo="8043", zona=_TUNJA, dia_visita="martes")

        editado = cliente_editado(original, a_fila(original) | {"barrio": "OTRO"}, _CATALOGO)

        assert editado.dia_visita == "martes"

    def test_la_zona_se_guarda_con_el_nombre_exacto_del_catalogo(self) -> None:
        """crear_zona colapsa los espacios y los nombres de la base traen dobles:
        construirla en vez de buscarla apuntaría a una zona inexistente."""
        original = _cliente("8043")

        editado = cliente_editado(original, a_fila(original), _CATALOGO)

        assert editado.zona is not None
        assert editado.zona.nombre == "(TUNJA):  NIEVES"

    def test_una_zona_que_no_esta_en_el_catalogo_se_rechaza(self) -> None:
        original = _cliente("8043")

        with pytest.raises(ZonaInvalida, match="no está en el catálogo"):
            cliente_editado(original, a_fila(original) | {"zona": "(TUNJA): INVENTADA"}, _CATALOGO)

    def test_solo_se_guardan_las_filas_que_cambiaron(self) -> None:
        """El editor devuelve la página entera en cada rerun; sin este filtro
        corregir un cliente escribiría los 50 de la página."""
        originales = [_cliente("8043"), _cliente("120", zona=_BARBOSA)]
        filas = [a_fila(originales[0]) | {"barrio": "SANTA ANA"}, a_fila(originales[1])]

        modificados = clientes_modificados(originales, filas, _CATALOGO)

        assert [c.codigo for c in modificados] == ["8043"]
        assert modificados[0].barrio == "SANTA ANA"

    def test_una_fila_de_un_codigo_desconocido_se_ignora(self) -> None:
        filas = [{"codigo": "9999", "barrio": "X"}]

        assert clientes_modificados([_cliente("8043")], filas, _CATALOGO) == []


class _RepositorioFalso:
    """Solo lo que usa ``aplicar_cambios`` del RepositorioClientes."""

    def __init__(self, falla_en: str | None = None) -> None:
        self.guardados: list[Cliente] = []
        self._falla_en = falla_en

    def guardar_cliente(self, cliente: Cliente) -> None:
        if cliente.codigo == self._falla_en:
            raise LookupError("no existe la zona 'X' en la tabla zonas")
        self.guardados.append(cliente)


class TestAplicarCambios:
    def test_solo_persiste_los_clientes_que_cambiaron(self) -> None:
        originales = [_cliente("8043"), _cliente("120", zona=_BARBOSA)]
        filas = [a_fila(originales[0]) | {"zona": "(BARBOSA):  CITE"}, a_fila(originales[1])]
        repositorio = _RepositorioFalso()

        resultado = aplicar_cambios(repositorio, originales, filas, _CATALOGO)

        assert resultado == ResultadoGuardado(1, ())
        assert [c.codigo for c in repositorio.guardados] == ["8043"]
        assert repositorio.guardados[0].zona == _BARBOSA

    def test_sin_cambios_no_toca_la_base(self) -> None:
        originales = [_cliente("8043")]
        repositorio = _RepositorioFalso()

        resultado = aplicar_cambios(repositorio, originales, [a_fila(originales[0])], _CATALOGO)

        assert resultado.guardados == 0
        assert repositorio.guardados == []

    def test_el_fallo_de_uno_no_frena_las_correcciones_buenas(self) -> None:
        """Se guarda cliente por cliente justamente por esto."""
        originales = [_cliente("8043"), _cliente("120", zona=_BARBOSA)]
        filas = [
            a_fila(originales[0]) | {"barrio": "SANTA ANA"},
            a_fila(originales[1]) | {"barrio": "CENTRO 2"},
        ]
        repositorio = _RepositorioFalso(falla_en="8043")

        resultado = aplicar_cambios(repositorio, originales, filas, _CATALOGO)

        assert resultado.guardados == 1
        assert [c.codigo for c in repositorio.guardados] == ["120"]
        assert "8043" in resultado.errores[0]

    def test_desactivar_un_cliente_lo_guarda_inactivo_sin_borrarlo(self) -> None:
        originales = [_cliente("8043")]
        repositorio = _RepositorioFalso()

        aplicar_cambios(repositorio, originales, [a_fila(originales[0]) | {"activo": False}], _CATALOGO)

        assert repositorio.guardados[0].activo is False
        assert repositorio.guardados[0].codigo == "8043"
