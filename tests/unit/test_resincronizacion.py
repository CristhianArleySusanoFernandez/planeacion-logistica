"""Pruebas de la resincronización en modo reporte: archivo contra base, sin tocar nada.

Todo acá se prueba con objetos de dominio armados a mano —no hay Supabase ni
Excel— porque lo que importa es el criterio: qué se actualiza, qué se rellena sin
pisar y, sobre todo, qué **no** se borra.
"""

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
from planeacion.infraestructura.adaptadores.entrada.cli.resincronizacion import (
    SIN_ORIGEN,
    DatosCompletos,
    FilaCliente,
    mapear_origenes,
    planear_clientes,
    planear_correcciones,
    planear_flota,
    planear_overrides,
    planear_zonas,
    reparar_mojibake,
    tiene_mojibake,
    zonas_a_desactivar,
)

_TUNJA = Municipio(nombre="TUNJA")
_OTROS = Municipio(nombre="OTROS")
_ZONA_NIEVES = Zona(nombre="(TUNJA): NIEVES", municipio=_TUNJA)
_ZONA_ASIS = Zona(nombre="(TUNJA): ASIS", municipio=_TUNJA)


class TestFlota:
    def test_la_ruta_se_actualiza_en_sitio_y_conserva_su_numero(self) -> None:
        """El numero es la identidad: las planeaciones guardadas siguen apuntando a
        la misma fila aunque hoy esa ruta tenga otro conductor y otro municipio."""
        base = [Carro(numero="13", conductor="CAMILO", municipio=_TUNJA)]
        archivo = [
            Carro(
                numero="13",
                conductor="RAUL 2",
                municipio=_OTROS,
                conductor_clave="RAUL",
                municipio_real="VILLA DELEYVA",
            )
        ]

        plan = planear_flota(archivo, base)

        assert [c.numero for c in plan.actualizadas] == ["13"]
        assert plan.nuevas == []
        campos = {(c.campo, c.antes, c.despues) for c in plan.cambios}
        assert ("conductor", "CAMILO", "RAUL 2") in campos
        assert ("municipio", "TUNJA", "OTROS") in campos
        assert ("municipio_real", None, "VILLA DELEYVA") in campos

    def test_una_ruta_que_no_cambio_no_se_reescribe(self) -> None:
        carro = Carro(numero="1", conductor="FABIAN 1", municipio=_TUNJA, conductor_clave="FABIAN")

        plan = planear_flota([carro], [carro])

        assert plan.sin_cambios == 1
        assert plan.a_guardar == []
        assert plan.cambios == []

    def test_el_lado_de_chiquinquira_viaja_como_texto_en_el_reporte(self) -> None:
        plan = planear_flota(
            [Carro(numero="3", lado_chiquinquira=ReglaChiquinquira.NORTE)], [Carro(numero="3")]
        )

        assert [(c.campo, c.despues) for c in plan.cambios] == [("lado_chiquinquira", "NORTE")]

    def test_cero_y_cero_coma_cero_no_son_un_cambio(self) -> None:
        """La columna es `numeric` y vuelve con la escala que tenga; sin normalizar,
        las 22 rutas aparecerían cambiadas en cada corrida."""
        plan = planear_flota(
            [Carro(numero="1", costo_diario=Decimal("0"))],
            [Carro(numero="1", costo_diario=Decimal("0.00"))],
        )

        assert plan.cambios == []

    def test_una_ruta_de_la_base_que_no_esta_en_el_archivo_se_desactiva_sin_borrarse(self) -> None:
        base = [Carro(numero="17", conductor="VIEJO", activo=True)]

        plan = planear_flota([], base)

        assert [c.numero for c in plan.desactivadas] == ["17"]
        assert plan.desactivadas[0].activo is False
        # Y sigue teniendo su conductor: desactivar no es vaciar.
        assert plan.desactivadas[0].conductor == "VIEJO"

    def test_una_ruta_ya_inactiva_no_se_reescribe(self) -> None:
        plan = planear_flota([], [Carro(numero="23", activo=False)])

        assert plan.a_guardar == []

    def test_la_placa_de_la_base_sobrevive_porque_el_archivo_no_la_trae(self) -> None:
        base = [Carro(numero="1", conductor="VIEJO", placa="SZN374")]

        plan = planear_flota([Carro(numero="1", conductor="FABIAN 1")], base)

        assert plan.actualizadas[0].placa == "SZN374"


class TestZonas:
    def test_las_zonas_nuevas_se_crean_con_el_municipio_del_prefijo(self) -> None:
        plan = planear_zonas(["(BARBOSA):  TRAPICHE", "MONIQUIRA"], [], {})

        assert [(z.nombre, z.municipio.nombre) for z in plan.nuevas] == [
            ("(BARBOSA): TRAPICHE", "BARBOSA"),
            ("MONIQUIRA", "OTROS"),
        ]

    def test_las_zonas_que_ya_no_estan_en_la_maestra_se_listan_pero_no_se_borran(self) -> None:
        """Con su número de clientes, que es lo que hace falta para decidirlo."""
        base = [_ZONA_NIEVES, _ZONA_ASIS]

        plan = planear_zonas(["(TUNJA): NIEVES"], base, {_ZONA_ASIS.nombre: 7})

        assert plan.nuevas == []
        assert plan.solo_en_base == [("(TUNJA): ASIS", 7)]

    def test_las_variantes_por_espacios_colapsan_en_una_sola_zona(self) -> None:
        plan = planear_zonas(["(TUNJA):  NIEVES", "(TUNJA): NIEVES  "], [], {})

        assert len(plan.nuevas) == 1

    def test_un_parentesis_sin_cerrar_se_reporta_porque_la_normalizacion_no_lo_arregla(self) -> None:
        plan = planear_zonas(["(CHIQUINQUIRA:   CHIQUIN NORTE RUTA 3"], [], {})

        assert plan.nombres_malformados == ["(CHIQUINQUIRA: CHIQUIN NORTE RUTA 3"]


class TestClientes:
    def test_un_cliente_nuevo_entra_con_documento_y_razon_social(self) -> None:
        plan = planear_clientes(
            [FilaCliente(codigo="111", ciudad="TUNJA", ruta="(TUNJA):  NIEVES")],
            {"111": DatosCompletos(documento="123", razon_social="TIENDA UNO")},
            [],
            {_ZONA_NIEVES.nombre: _ZONA_NIEVES},
        )

        assert len(plan.nuevos) == 1
        nuevo = plan.nuevos[0]
        assert (nuevo.documento, nuevo.razon_social) == ("123", "TIENDA UNO")
        assert nuevo.zona == _ZONA_NIEVES

    def test_el_documento_ya_cargado_en_la_app_no_se_pisa(self) -> None:
        """Asimetría a propósito: documento y razón social solo se RELLENAN."""
        base = [Cliente(codigo="111", documento="CORREGIDO A MANO", zona=_ZONA_NIEVES)]

        plan = planear_clientes(
            [FilaCliente(codigo="111", ruta="(TUNJA): NIEVES")],
            {"111": DatosCompletos(documento="DE LA HOJA", razon_social="TIENDA")},
            base,
            {_ZONA_NIEVES.nombre: _ZONA_NIEVES},
        )

        assert plan.actualizados[0].documento == "CORREGIDO A MANO"
        # La razón social sí se rellena: estaba vacía.
        assert plan.actualizados[0].razon_social == "TIENDA"
        assert [(c.campo, c.despues) for c in plan.rellenados] == [("razon_social", "TIENDA")]

    def test_el_cambio_de_zona_queda_como_antes_y_despues(self) -> None:
        base = [Cliente(codigo="111", zona=_ZONA_ASIS)]

        plan = planear_clientes(
            [FilaCliente(codigo="111", ruta="(TUNJA): NIEVES")],
            {},
            base,
            {_ZONA_NIEVES.nombre: _ZONA_NIEVES},
        )

        assert [(c.antes, c.despues) for c in plan.cambios_de_zona] == [("(TUNJA): ASIS", "(TUNJA): NIEVES")]

    def test_si_la_zona_de_la_maestra_no_existe_el_cliente_conserva_la_que_tenia(self) -> None:
        """Dejarlo sin zona lo mandaría al pozo de los #N/D por un error de catálogo."""
        base = [Cliente(codigo="111", zona=_ZONA_ASIS)]

        plan = planear_clientes([FilaCliente(codigo="111", ruta="ZONA QUE NO EXISTE")], {}, base, {})

        assert plan.actualizados == [] or plan.actualizados[0].zona == _ZONA_ASIS
        assert plan.cambios_de_zona == []
        assert [(c.campo, c.despues) for c in plan.zonas_no_encontradas] == [
            ("zona inexistente", "ZONA QUE NO EXISTE")
        ]

    def test_los_clientes_de_la_base_que_no_estan_en_la_maestra_no_se_borran(self) -> None:
        base = [Cliente(codigo="111"), Cliente(codigo="222")]

        plan = planear_clientes([FilaCliente(codigo="111")], {}, base, {})

        assert plan.solo_en_base == ["222"]
        assert all(cliente.codigo != "222" for cliente in plan.a_guardar)

    def test_un_cliente_identico_no_se_reescribe(self) -> None:
        cliente = Cliente(codigo="111", ciudad="TUNJA", barrio="CENTRO", direccion="CL 1")

        plan = planear_clientes(
            [FilaCliente(codigo="111", ciudad="TUNJA", barrio="CENTRO", direccion="CL 1")],
            {},
            [cliente],
            {},
        )

        assert plan.sin_cambios == 1
        assert plan.a_guardar == []

    def test_un_codigo_repetido_en_la_maestra_gana_la_primera_aparicion(self) -> None:
        plan = planear_clientes(
            [FilaCliente(codigo="111", ciudad="PRIMERA"), FilaCliente(codigo="111", ciudad="SEGUNDA")],
            {},
            [],
            {},
        )

        assert plan.duplicados_en_archivo == 1
        assert [c.ciudad for c in plan.nuevos] == ["PRIMERA"]

    def test_un_codigo_repetido_con_zonas_distintas_se_reporta_y_no_se_aplica(self) -> None:
        actual = Cliente(codigo="111", zona=Zona(nombre="(TUNJA): VIEJA", municipio=Municipio("TUNJA")))
        zonas = {
            "(TUNJA): UNA": Zona(nombre="(TUNJA): UNA", municipio=Municipio("TUNJA")),
            "(TUNJA): OTRA": Zona(nombre="(TUNJA): OTRA", municipio=Municipio("TUNJA")),
        }
        plan = planear_clientes(
            [
                FilaCliente(codigo="111", ruta="(TUNJA): UNA"),
                FilaCliente(codigo="111", ruta="(TUNJA): OTRA"),
                FilaCliente(codigo="222", ruta="(TUNJA): UNA"),
                FilaCliente(codigo="222", ruta="(TUNJA):  UNA"),
            ],
            {},
            [actual],
            zonas,
        )

        assert [c.clave for c in plan.duplicados_con_zonas_distintas] == ["111"]
        assert plan.duplicados_con_zonas_distintas[0].despues == "(TUNJA): OTRA | (TUNJA): UNA"
        assert plan.duplicados_en_archivo == 1  # el 222, misma zona salvo espacios
        assert [c.codigo for c in plan.a_guardar] == ["222"]
        assert plan.cambios_de_zona == []  # el 111 conserva (TUNJA): VIEJA


class TestCorreccionesYOverrides:
    def test_una_correccion_nueva_se_agrega_y_la_que_solo_esta_en_la_base_se_lista(self) -> None:
        base = [CorreccionUbicacion(cliente_codigo="999", ciudad_real="VIEJA", barrio_real=None)]
        archivo = [CorreccionUbicacion(cliente_codigo="111", ciudad_real="COMBITA", barrio_real=None)]

        plan = planear_correcciones(archivo, base)

        assert [c.cliente_codigo for c in plan.nuevas] == ["111"]
        assert plan.solo_en_base == ["999"]

    def test_un_override_cuya_zona_no_existe_se_descarta_y_se_reporta(self) -> None:
        """La hoja "martha ojo" está llena de restos de fórmulas; la FK los rechazaría."""
        archivo = [
            OverrideZona(cliente_codigo="111", zona_nombre="(TUNJA):  NIEVES"),
            OverrideZona(cliente_codigo="222", zona_nombre="#N/A"),
        ]

        plan = planear_overrides(archivo, [], [_ZONA_NIEVES.nombre])

        assert [o.cliente_codigo for o in plan.nuevos] == ["111"]
        assert plan.nuevos[0].zona_nombre == "(TUNJA): NIEVES"
        assert [(c.clave, c.despues) for c in plan.zonas_no_encontradas] == [("222", "#N/A")]

    def test_un_override_que_cambio_de_zona_se_actualiza(self) -> None:
        base = [OverrideZona(cliente_codigo="111", zona_nombre=_ZONA_ASIS.nombre)]
        archivo = [OverrideZona(cliente_codigo="111", zona_nombre=_ZONA_NIEVES.nombre)]

        plan = planear_overrides(archivo, base, [_ZONA_NIEVES.nombre, _ZONA_ASIS.nombre])

        assert [(c.antes, c.despues) for c in plan.cambios] == [("(TUNJA): ASIS", "(TUNJA): NIEVES")]


class TestCodificacion:
    def test_repara_la_doble_codificacion_mas_comun(self) -> None:
        assert reparar_mojibake("PEÃ‘A LUENGAS YENY CAROLINA") == "PEÑA LUENGAS YENY CAROLINA"
        assert reparar_mojibake("NIÃ‘O SAAVEDRA DORIS ROCIO") == "NIÑO SAAVEDRA DORIS ROCIO"

    def test_repara_un_nombre_que_mezcla_los_dos_rangos(self) -> None:
        """El caso que obliga a probar tabla por carácter: el ``\x8d`` solo existe en
        latin-1 y el ``“`` solo en cp1252, así que ninguna de las dos sola alcanza."""
        assert reparar_mojibake("PHA LOGÃ\x8dSTICA Y DISTRIBUCIÃ“N SAS") == (
            "PHA LOGÍSTICA Y DISTRIBUCIÓN SAS"
        )

    def test_un_texto_sano_no_se_toca(self) -> None:
        assert reparar_mojibake("MARIA LIBIA SOLER VELANDIA") == "MARIA LIBIA SOLER VELANDIA"
        assert reparar_mojibake("BAREÑO ANGEL") == "BAREÑO ANGEL"
        assert reparar_mojibake(None) is None

    def test_lo_que_no_se_puede_reparar_vuelve_intacto_y_se_puede_detectar(self) -> None:
        """Nunca inventa: si la doble codificación no se deshace, queda para revisar."""
        roto = "Ã" + chr(0x100)  # un carácter que ninguna de las dos tablas representa

        assert reparar_mojibake(roto) == roto
        assert tiene_mojibake(roto)
        assert not tiene_mojibake("PEÑA")


def _fila(codigo: str, ruta: str) -> FilaCliente:
    return FilaCliente(codigo=codigo, direccion="", ciudad="", barrio="", ruta=ruta)


def _cliente(codigo: str, zona: Zona | None) -> Cliente:
    return Cliente(codigo=codigo, razon_social=codigo, zona=zona)


class TestMapeoDeOrigenes:
    """De qué zonas viejas viene cada zona nueva.

    Es lo que alimenta la herencia de repertorio, así que las fracciones tienen
    que ser exactas: con ellas se decide qué carro atiende una zona que la
    operación nunca vio con ese nombre.
    """

    _ZONA_NUEVA = Zona(nombre="(TUNJA): NIEVES", municipio=_TUNJA)
    _ZONAS = {_ZONA_NUEVA.nombre: _ZONA_NUEVA}

    def test_un_renombre_puro_deja_un_solo_origen_al_100(self) -> None:
        filas = [_fila("1", "(TUNJA): NIEVES"), _fila("2", "(TUNJA): NIEVES")]
        base = [_cliente("1", _ZONA_ASIS), _cliente("2", _ZONA_ASIS)]

        origenes = mapear_origenes(filas, base, self._ZONAS)

        assert len(origenes) == 1
        assert (origenes[0].zona_vieja, origenes[0].clientes, origenes[0].fraccion) == (
            _ZONA_ASIS.nombre,
            2,
            1.0,
        )

    def test_una_fusion_reparte_las_fracciones_y_suman_uno(self) -> None:
        otra = Zona(nombre="(TUNJA): OTRA", municipio=_TUNJA)
        filas = [_fila(str(i), "(TUNJA): NIEVES") for i in range(5)]
        base = [_cliente("0", _ZONA_ASIS), _cliente("1", _ZONA_ASIS), _cliente("2", _ZONA_ASIS)]
        base += [_cliente("3", otra), _cliente("4", otra)]

        origenes = mapear_origenes(filas, base, self._ZONAS)

        fracciones = {o.zona_vieja: o.fraccion for o in origenes}
        assert fracciones == {_ZONA_ASIS.nombre: 0.6, otra.nombre: 0.4}
        assert sum(fracciones.values()) == 1.0

    def test_el_origen_mayoritario_va_primero(self) -> None:
        """La tabla se lee como "esta zona es sobre todo la vieja X"."""
        otra = Zona(nombre="(TUNJA): OTRA", municipio=_TUNJA)
        filas = [_fila("1", "(TUNJA): NIEVES"), _fila("2", "(TUNJA): NIEVES")]
        base = [_cliente("1", otra), _cliente("2", _ZONA_ASIS)]
        filas.append(_fila("3", "(TUNJA): NIEVES"))
        base.append(_cliente("3", _ZONA_ASIS))

        origenes = mapear_origenes(filas, base, self._ZONAS)

        assert origenes[0].zona_vieja == _ZONA_ASIS.nombre

    def test_el_cliente_que_no_cambio_es_origen_de_su_propia_zona(self) -> None:
        """Si la zona no cambió de nombre, su mejor candidato a repertorio es el
        suyo: aparece como origen de sí misma y no como un hueco."""
        filas = [_fila("1", "(TUNJA): NIEVES")]
        base = [_cliente("1", self._ZONA_NUEVA)]

        origenes = mapear_origenes(filas, base, self._ZONAS)

        assert origenes[0].zona_vieja == self._ZONA_NUEVA.nombre

    def test_el_cliente_nuevo_no_aporta_peso_a_ninguna_zona_vieja(self) -> None:
        filas = [_fila("1", "(TUNJA): NIEVES"), _fila("2", "(TUNJA): NIEVES")]
        base = [_cliente("1", _ZONA_ASIS)]

        origenes = mapear_origenes(filas, base, self._ZONAS)

        por_origen = {o.zona_vieja: o.clientes for o in origenes}
        assert por_origen == {_ZONA_ASIS.nombre: 1, SIN_ORIGEN: 1}

    def test_una_zona_que_no_existe_en_el_catalogo_no_entra(self) -> None:
        """Si la zona no se pudo crear, mapearla sería prometer una herencia que
        no tiene dónde escribirse."""
        filas = [_fila("1", "(TUNJA): INVENTADA")]

        assert mapear_origenes(filas, [_cliente("1", _ZONA_ASIS)], self._ZONAS) == []

    def test_el_cliente_repetido_en_la_hoja_se_cuenta_una_vez(self) -> None:
        """La maestra trae filas duplicadas; gana la primera, como en el plan de
        clientes. Contarlo dos veces inflaría su peso en la herencia."""
        filas = [_fila("1", "(TUNJA): NIEVES"), _fila("1", "(TUNJA): NIEVES")]

        origenes = mapear_origenes(filas, [_cliente("1", _ZONA_ASIS)], self._ZONAS)

        assert origenes[0].total_de_la_zona == 1


class TestZonasADesactivar:
    def test_la_zona_sin_clientes_se_apaga_sin_perder_su_municipio(self) -> None:
        apagadas = zonas_a_desactivar([_ZONA_NIEVES, _ZONA_ASIS], {_ZONA_NIEVES.nombre: 12})

        assert [(z.nombre, z.activa, z.municipio) for z in apagadas] == [(_ZONA_ASIS.nombre, False, _TUNJA)]

    def test_una_zona_ya_inactiva_no_se_vuelve_a_listar(self) -> None:
        """Para que el reporte no repita todas las corridas lo mismo."""
        inactiva = Zona(nombre="(TUNJA): VIEJA", municipio=_TUNJA, activa=False)

        assert zonas_a_desactivar([inactiva], {}) == []

    def test_la_zona_con_clientes_no_se_toca(self) -> None:
        assert zonas_a_desactivar([_ZONA_NIEVES], {_ZONA_NIEVES.nombre: 1}) == []

    def test_conserva_la_regla_de_chiquinquira(self) -> None:
        """La zona puede volver: apagarla no es olvidar de qué lado queda."""
        zona = Zona(
            nombre="(CHIQUINQUIRA): NORTE",
            municipio=Municipio(nombre="CHIQUINQUIRA"),
            regla_chiquinquira=ReglaChiquinquira.NORTE,
        )

        assert zonas_a_desactivar([zona], {})[0].regla_chiquinquira == ReglaChiquinquira.NORTE
