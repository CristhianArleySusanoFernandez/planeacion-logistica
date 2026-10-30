"""Pruebas del cotejo entre la propuesta automática y la planeación manual."""

from decimal import Decimal

from planeacion.domain.modelo import AsignacionZona, Carro
from planeacion.domain.servicios.comparador_asignaciones import comparar_asignaciones
from planeacion.domain.servicios.parseo_zonas import crear_zona


def _asignacion(nombre_zona: str, numero_carro: str, clientes: int = 10) -> AsignacionZona:
    return AsignacionZona(
        zona=crear_zona(nombre_zona),
        carro=Carro(numero=numero_carro),
        facturas=clientes,
        clientes=clientes,
        pesos=Decimal("1000"),
        kilos=Decimal("5"),
    )


def test_cuenta_coincidencias_y_diferencias() -> None:
    manual = {"(TUNJA):  NIEVES": "14", "(TUNJA):  PATRIOTAS": "12", "(BARBOSA):  CENTRO": "3"}
    propuesta = [
        _asignacion("(TUNJA):  NIEVES", "14"),
        _asignacion("(TUNJA):  PATRIOTAS", "13"),
        _asignacion("(BARBOSA):  CENTRO", "3"),
    ]

    comparacion = comparar_asignaciones(manual, propuesta)

    assert comparacion.coincidencias == 2
    assert comparacion.comparables == 3
    assert comparacion.porcentaje == 2 / 3
    assert [d.zona for d in comparacion.diferencias] == ["(TUNJA): PATRIOTAS"]


def test_la_diferencia_trae_los_dos_carros_y_el_municipio() -> None:
    """Es la fila del CSV: sin el municipio y los dos carros no se puede analizar
    si una zona difiere siempre por la misma razón."""
    comparacion = comparar_asignaciones(
        {"(BARBOSA):  CENTRO": "3"}, [_asignacion("(BARBOSA):  CENTRO", "5", clientes=26)]
    )

    diferencia = comparacion.diferencias[0]
    assert (diferencia.municipio, diferencia.carro_manual, diferencia.carro_propuesto) == (
        "BARBOSA",
        "3",
        "5",
    )
    assert (diferencia.clientes, diferencia.pesos) == (26, Decimal("1000"))


def test_los_espacios_multiples_no_cuentan_como_zona_distinta() -> None:
    """El mismo nombre aparece con distinta cantidad de espacios entre las hojas
    del Excel; sin normalizar, ninguna zona cruzaría y todo daría 0 %."""
    comparacion = comparar_asignaciones(
        {"(TUNJA):     NIEVES": "14"}, [_asignacion("(TUNJA):  NIEVES", "14")]
    )

    assert comparacion.coincidencias == 1
    assert comparacion.sin_propuesta == ()


def test_las_zonas_que_la_app_no_asigno_van_aparte_y_no_cuentan_como_diferencia() -> None:
    """Una zona del manual que la app no produjo (cliente fuera de la maestra) es
    un hueco de cobertura, no un desacuerdo de reparto: mezclarlas escondería
    cuál de los dos problemas hay que atacar."""
    manual = {"(TUNJA):  NIEVES": "14", "(TUNJA):  DESCONOCIDA": "12"}

    comparacion = comparar_asignaciones(manual, [_asignacion("(TUNJA):  NIEVES", "14")])

    assert comparacion.diferencias == ()
    assert comparacion.sin_propuesta == ("(TUNJA): DESCONOCIDA",)
    assert comparacion.comparables == 1


def test_los_dos_porcentajes_se_separan_cuando_hay_zonas_sin_propuesta() -> None:
    """Principal sobre la intersección (1 de 1); pesimista sobre todo el manual
    (1 de 2), contando lo no cubierto como fallo."""
    manual = {"(TUNJA):  NIEVES": "14", "(TUNJA):  DESCONOCIDA": "12"}

    comparacion = comparar_asignaciones(manual, [_asignacion("(TUNJA):  NIEVES", "14")])

    assert comparacion.porcentaje == 1.0
    assert comparacion.porcentaje_pesimista == 0.5


def test_sin_zonas_comparables_los_porcentajes_son_cero_y_no_revientan() -> None:
    comparacion = comparar_asignaciones({}, [])

    assert (comparacion.porcentaje, comparacion.porcentaje_pesimista) == (0.0, 0.0)


def test_las_zonas_que_la_app_asigno_de_mas_no_afectan_el_conteo() -> None:
    """El denominador siempre es lo que Rudy planeó: si la app propone una zona
    que ese día no estaba en PLANEACION, no hay contra qué compararla."""
    comparacion = comparar_asignaciones(
        {"(TUNJA):  NIEVES": "14"},
        [_asignacion("(TUNJA):  NIEVES", "14"), _asignacion("(TUNJA):  EXTRA", "12")],
    )

    assert (comparacion.zonas_manuales, comparacion.comparables, comparacion.coincidencias) == (1, 1, 1)


class TestCoincidenciaPorCamion:
    """Dos planillas del mismo camión no son dos vehículos distintos.

    Cinco conductores llevan dos planillas (Fabián 1 y 2, Angélica 1 y 2, Raúl,
    Javier Reyes, Carlos) y la operación intercambia carga entre las dos según el
    día, para que lleguen parejas a bodega. Si la app pone una zona en la planilla
    1 y la hoja la tiene en la 2, la carga va en el mismo camión y solo cambia en
    cuál de las dos hojas aparece. Medir solo por planilla castiga eso como si
    fuera un error de reparto; medir solo por camión esconde los errores reales.
    Por eso van las dos.
    """

    _CLAVES = {"14": "JAVIER REYES", "15": "JAVIER REYES", "18": "JOSE YOVANY", "19": "LUIS EDUARDO"}

    def _con_clave(self, nombre_zona: str, numero_carro: str) -> AsignacionZona:
        asignacion = _asignacion(nombre_zona, numero_carro)
        return AsignacionZona(
            zona=asignacion.zona,
            carro=Carro(numero=numero_carro, conductor_clave=self._CLAVES[numero_carro]),
            facturas=asignacion.facturas,
            clientes=asignacion.clientes,
            pesos=asignacion.pesos,
            kilos=asignacion.kilos,
        )

    def test_el_cambio_de_planilla_falla_por_planilla_y_acierta_por_camion(self) -> None:
        comparacion = comparar_asignaciones(
            {"NUEVO COLON": "14"}, [self._con_clave("NUEVO COLON", "15")], self._CLAVES
        )

        assert (comparacion.coincidencias, comparacion.porcentaje) == (0, 0.0)
        assert (comparacion.coincidencias_por_camion, comparacion.porcentaje_por_camion) == (1, 1.0)
        assert comparacion.diferencias[0].mismo_conductor is True

    def test_el_cambio_de_conductor_falla_en_las_dos(self) -> None:
        """La carga va a otro camión: eso es una diferencia de verdad."""
        comparacion = comparar_asignaciones(
            {"SANTA ANA": "19"}, [self._con_clave("SANTA ANA", "18")], self._CLAVES
        )

        assert comparacion.coincidencias == 0
        assert comparacion.coincidencias_por_camion == 0
        assert comparacion.diferencias[0].mismo_conductor is False

    def test_un_acierto_por_planilla_tambien_lo_es_por_camion(self) -> None:
        comparacion = comparar_asignaciones(
            {"NUEVO COLON": "14"}, [self._con_clave("NUEVO COLON", "14")], self._CLAVES
        )

        assert comparacion.porcentaje == comparacion.porcentaje_por_camion == 1.0
        assert comparacion.mismo_camion == 0

    def test_la_mezcla_de_los_dos_casos_cuenta_cada_uno_donde_va(self) -> None:
        manual = {"NUEVO COLON": "14", "SANTA ANA": "19", "TIBANA": "15"}
        propuesta = [
            self._con_clave("NUEVO COLON", "15"),  # otra planilla del mismo camión
            self._con_clave("SANTA ANA", "18"),  # otro camión
            self._con_clave("TIBANA", "15"),  # igual
        ]

        comparacion = comparar_asignaciones(manual, propuesta, self._CLAVES)

        assert (comparacion.coincidencias, comparacion.comparables) == (1, 3)
        assert comparacion.coincidencias_por_camion == 2
        assert comparacion.mismo_camion == 1

    def test_sin_las_claves_no_se_inventa_igualdad(self) -> None:
        """Sin saber quién maneja cada ruta no se puede afirmar que sea el mismo
        camión: la medición por camión cae a la de planilla, que es lo estricto."""
        comparacion = comparar_asignaciones({"NUEVO COLON": "14"}, [self._con_clave("NUEVO COLON", "15")])

        assert comparacion.coincidencias_por_camion == comparacion.coincidencias == 0

    def test_una_ruta_del_manual_que_no_esta_en_la_flota_no_cuenta_como_mismo_camion(self) -> None:
        """La ruta 23 de refuerzo aparece en hojas viejas y no está en la flota:
        sin su clave, la diferencia se cuenta entera."""
        comparacion = comparar_asignaciones(
            {"NUEVO COLON": "23"}, [self._con_clave("NUEVO COLON", "14")], self._CLAVES
        )

        assert comparacion.coincidencias_por_camion == 0
        assert comparacion.diferencias[0].mismo_conductor is False
