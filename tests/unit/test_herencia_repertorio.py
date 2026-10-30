"""Pruebas de la herencia de repertorio (cambio de maestra de octubre de 2026).

Lo que se protege acá es la costumbre de la operación: meses de observaciones de
qué carro atiende qué zona cada día, que el cambio de nombres dejó colgando. Si la
herencia se equivoca, el Paso 3 propone carros que nunca pasaron por esa zona, y
eso se ve en la calle.

Las dos reglas que más importan: lo sembrado con el nombre nuevo **manda** sobre
lo heredado, y un par con frecuencia 0 **no es** un par ausente.
"""

from planeacion.application.puertos.salida.repositorios import ParRepertorio
from planeacion.infraestructura.adaptadores.entrada.cli.herencia import (
    ENCABEZADO_MAPEO,
    SIN_ORIGEN,
    Origen,
    heredar,
    leer_mapeo,
)

_LUNES = "LUNES"
_MARTES = "MARTES"


def _origen(nueva: str, vieja: str, clientes: int, total: int) -> Origen:
    return Origen(zona_nueva=nueva, zona_vieja=vieja, clientes=clientes, total_de_la_zona=total)


def _frecuencias(*pares: tuple[str, str, str, int]) -> dict[ParRepertorio, int]:
    return {
        ParRepertorio(carro, zona, dia, frecuencia=frecuencia): frecuencia
        for carro, zona, dia, frecuencia in pares
    }


class TestRenombrePuro:
    def test_la_zona_renombrada_hereda_el_repertorio_tal_cual(self) -> None:
        """El 100 % de los clientes viene de una sola zona: no hay nada que mezclar."""
        origenes = [_origen("NIEVES 1", "NIEVES", 80, 80)]
        frecuencias = _frecuencias(("14", "NIEVES", _LUNES, 12), ("15", "NIEVES", _LUNES, 3))

        herencia = heredar(origenes, frecuencias)

        assert set(herencia.pares) == {
            ParRepertorio("14", "NIEVES 1", _LUNES, frecuencia=12),
            ParRepertorio("15", "NIEVES 1", _LUNES, frecuencia=3),
        }

    def test_hereda_cada_dia_por_separado(self) -> None:
        """El repertorio es por día: el carro del lunes no es el del martes."""
        origenes = [_origen("NIEVES 1", "NIEVES", 10, 10)]
        frecuencias = _frecuencias(("14", "NIEVES", _LUNES, 9), ("20", "NIEVES", _MARTES, 7))

        herencia = heredar(origenes, frecuencias)

        assert herencia.pares_por_dia == {_LUNES: 1, _MARTES: 1}
        assert ParRepertorio("20", "NIEVES 1", _MARTES, frecuencia=7) in herencia.pares


class TestFusion:
    def test_una_fusion_60_40_pondera_las_frecuencias(self) -> None:
        origenes = [_origen("CENTRO", "CENTRO A", 60, 100), _origen("CENTRO", "CENTRO B", 40, 100)]
        frecuencias = _frecuencias(("14", "CENTRO A", _LUNES, 10), ("14", "CENTRO B", _LUNES, 5))

        herencia = heredar(origenes, frecuencias)

        # 0,6 × 10 + 0,4 × 5 = 8
        assert herencia.pares == [ParRepertorio("14", "CENTRO", _LUNES, frecuencia=8)]

    def test_un_carro_que_solo_estaba_en_un_origen_entra_con_su_peso(self) -> None:
        """Hereda, pero menos: lo atendía la zona de la que vino poca gente."""
        origenes = [_origen("CENTRO", "CENTRO A", 90, 100), _origen("CENTRO", "CENTRO B", 10, 100)]
        frecuencias = _frecuencias(("14", "CENTRO A", _LUNES, 20), ("15", "CENTRO B", _LUNES, 20))

        herencia = heredar(origenes, frecuencias)

        por_carro = {par.numero_carro: par.frecuencia for par in herencia.pares}
        assert por_carro == {"14": 18, "15": 2}

    def test_un_aporte_chico_no_se_redondea_a_cero(self) -> None:
        """0,4 redondeado a 0 diría "este carro no atiende la zona", que es otra
        cosa que "la atiende poco". El mínimo es 1."""
        origenes = [_origen("CENTRO", "CENTRO A", 96, 100), _origen("CENTRO", "CENTRO B", 4, 100)]
        frecuencias = _frecuencias(("15", "CENTRO B", _LUNES, 10))

        herencia = heredar(origenes, frecuencias)

        assert herencia.pares == [ParRepertorio("15", "CENTRO", _LUNES, frecuencia=1)]

    def test_los_clientes_nuevos_no_aportan_repertorio(self) -> None:
        """De un cliente que no estaba en la base no se sabe qué carro lo atendía;
        su peso diluye la mezcla sin sumar nada, que es lo correcto."""
        origenes = [_origen("CENTRO", "CENTRO A", 50, 100), _origen("CENTRO", SIN_ORIGEN, 50, 100)]
        frecuencias = _frecuencias(("14", "CENTRO A", _LUNES, 10))

        herencia = heredar(origenes, frecuencias)

        assert herencia.pares == [ParRepertorio("14", "CENTRO", _LUNES, frecuencia=5)]


class TestMitadesDeUnaMisma:
    def test_las_dos_mitades_heredan_lo_mismo(self) -> None:
        """Las zonas partidas en dos existen para que las dos planillas del mismo
        camión lleguen parejas a bodega, y las mitades se intercambian según el
        día. Que hereden lo mismo es lo esperado, no un error."""
        origenes = [
            _origen("OCCIDENTE 1", "OCCIDENTE", 100, 100),
            _origen("OCCIDENTE 2", "OCCIDENTE", 100, 100),
        ]
        frecuencias = _frecuencias(("14", "OCCIDENTE", _LUNES, 8))

        herencia = heredar(origenes, frecuencias)

        assert herencia.pares == [
            ParRepertorio("14", "OCCIDENTE 1", _LUNES, frecuencia=8),
            ParRepertorio("14", "OCCIDENTE 2", _LUNES, frecuencia=8),
        ]


class TestLoSembradoManda:
    def test_un_dia_con_repertorio_propio_no_se_toca(self) -> None:
        """La herencia es una estimación; lo que la operación hizo con el nombre
        nuevo es un hecho."""
        origenes = [_origen("NIEVES 1", "NIEVES", 10, 10)]
        frecuencias = _frecuencias(("14", "NIEVES", _LUNES, 12), ("20", "NIEVES 1", _LUNES, 1))

        herencia = heredar(origenes, frecuencias)

        assert herencia.pares == []
        assert herencia.dias_respetados == {"NIEVES 1": {_LUNES}}

    def test_el_dia_sembrado_se_respeta_y_los_otros_se_rellenan(self) -> None:
        """Una sola semana de archivos cubre un día por zona; los demás los tapa
        la herencia."""
        origenes = [_origen("NIEVES 1", "NIEVES", 10, 10)]
        frecuencias = _frecuencias(
            ("14", "NIEVES", _LUNES, 12),
            ("14", "NIEVES", _MARTES, 9),
            ("20", "NIEVES 1", _LUNES, 1),
        )

        herencia = heredar(origenes, frecuencias)

        assert herencia.pares == [ParRepertorio("14", "NIEVES 1", _MARTES, frecuencia=9)]

    def test_el_dia_sembrado_se_respeta_aunque_el_carro_sea_otro(self) -> None:
        """Si la operación cambió de carro, la herencia no puede devolver el viejo:
        el día entero se respeta, no par por par."""
        origenes = [_origen("NIEVES 1", "NIEVES", 10, 10)]
        frecuencias = _frecuencias(("14", "NIEVES", _LUNES, 30), ("21", "NIEVES 1", _LUNES, 1))

        herencia = heredar(origenes, frecuencias)

        assert all(par.numero_carro != "14" for par in herencia.pares)


class TestFrecuenciaCero:
    def test_un_par_de_origen_en_cero_hereda_cero(self) -> None:
        """Un 0 lo puso alguien a mano: es "este carro NO atiende esta zona ese
        día". Heredarlo como ausencia perdería la decisión."""
        origenes = [_origen("NIEVES 1", "NIEVES", 10, 10)]
        frecuencias = _frecuencias(("14", "NIEVES", _LUNES, 0))

        herencia = heredar(origenes, frecuencias)

        assert herencia.pares == [ParRepertorio("14", "NIEVES 1", _LUNES, frecuencia=0)]

    def test_un_carro_sin_par_en_ningun_origen_no_se_estrena(self) -> None:
        """La herencia propaga lo que existe; no le inventa carros a la zona."""
        origenes = [_origen("NIEVES 1", "NIEVES", 10, 10)]
        frecuencias = _frecuencias(("14", "NIEVES", _LUNES, 5), ("22", "OTRA ZONA", _LUNES, 5))

        herencia = heredar(origenes, frecuencias)

        assert [par.numero_carro for par in herencia.pares] == ["14"]


class TestZonasEspeciales:
    def test_una_zona_especial_no_hereda_nada(self) -> None:
        """Un cliente que pide esporádicamente y en grande no tiene costumbre que
        heredar: se despacha con el vehículo que convenga ese día."""
        origenes = [_origen("(TUNJA): ESTADIO REMONTA", "NIEVES", 1, 1)]
        frecuencias = _frecuencias(("14", "NIEVES", _LUNES, 12))

        herencia = heredar(origenes, frecuencias, especiales=["ESTADIO REMONTA"])

        assert herencia.pares == []
        assert herencia.especiales_ignoradas == ["(TUNJA): ESTADIO REMONTA"]

    def test_la_especial_se_reconoce_con_y_sin_prefijo_de_municipio(self) -> None:
        """La maestra las escribe de las dos maneras: `(TUNJA):PIZZA NOSTRA` y
        `COMFABOY` pelado."""
        origenes = [_origen("(TUNJA):PIZZA NOSTRA", "NIEVES", 1, 1), _origen("COMFABOY", "NIEVES", 1, 1)]
        frecuencias = _frecuencias(("14", "NIEVES", _LUNES, 12))

        herencia = heredar(origenes, frecuencias, especiales=["PIZZA NOSTRA", "(TUNJA): COMFABOY"])

        assert herencia.pares == []
        assert len(herencia.especiales_ignoradas) == 2

    def test_una_especial_no_cuenta_como_zona_sin_repertorio(self) -> None:
        """No tener repertorio es su estado normal: avisarlo sería ruido."""
        origenes = [_origen("COMFABOY", "NIEVES", 1, 1)]

        herencia = heredar(origenes, {}, especiales=["COMFABOY"])

        assert herencia.sin_ningun_par == []


class TestZonasSinPar:
    def test_la_zona_cuyo_origen_no_tenia_repertorio_se_reporta(self) -> None:
        """Sin ningún par no tiene carro elegible: hay que mirarla a mano."""
        origenes = [_origen("SACHICA", "ZONA SIN REPERTORIO", 5, 5)]

        herencia = heredar(origenes, {})

        assert herencia.sin_ningun_par == ["SACHICA"]

    def test_la_zona_que_hereda_algo_no_se_reporta(self) -> None:
        origenes = [_origen("NIEVES 1", "NIEVES", 10, 10)]

        herencia = heredar(origenes, _frecuencias(("14", "NIEVES", _LUNES, 5)))

        assert herencia.sin_ningun_par == []


class TestOrigenDesactivado:
    def test_una_zona_de_origen_inactiva_igual_hereda(self) -> None:
        """Las 124 zonas viejas quedaron desactivadas al aplicar la maestra nueva
        justamente por no tener clientes, y son el origen de toda la herencia. Si
        la lectura del repertorio las filtrara por `activa`, la herencia saldría
        vacía sin dar error: no habría nada de dónde heredar.

        La herencia trabaja sobre nombres, así que acá lo que se fija es que no se
        le agregue ningún filtro por estado de la zona.
        """
        origenes = [_origen("CHIQUIN NORTE RUTA 3 - 4", "CHIQUIN RUTA 1 NORTE", 339, 339)]
        # El par viene de una zona que ya está en activa = false.
        frecuencias = _frecuencias(("3", "CHIQUIN RUTA 1 NORTE", _LUNES, 18))

        herencia = heredar(origenes, frecuencias)

        assert herencia.pares == [ParRepertorio("3", "CHIQUIN NORTE RUTA 3 - 4", _LUNES, frecuencia=18)]


class TestLecturaDelCsv:
    def test_lee_las_filas_y_saltea_el_encabezado(self) -> None:
        filas = [list(ENCABEZADO_MAPEO), ["CENTRO", "CENTRO A", "60", "100", "0.6000"]]

        origenes = leer_mapeo(filas)

        assert len(origenes) == 1
        assert origenes[0].peso == 0.6

    def test_el_peso_se_recalcula_y_no_se_lee_del_archivo(self) -> None:
        """La columna `fraccion` del CSV es para leerla en Excel; la que manda es
        la división, porque un redondeo a cuatro decimales no tiene por qué
        decidir una frecuencia."""
        origenes = leer_mapeo([["CENTRO", "CENTRO A", "1", "3", "0.0000"]])

        assert origenes[0].peso == 1 / 3

    def test_una_fila_con_numeros_ilegibles_se_descarta_sin_reventar(self) -> None:
        """El archivo lo puede haber tocado alguien en Excel; una fila rota no
        justifica perder las otras doscientas."""
        filas = [["CENTRO", "CENTRO A", "sesenta", "100", ""], ["CENTRO", "CENTRO B", "40", "100", ""]]

        origenes = leer_mapeo(filas)

        assert [origen.zona_vieja for origen in origenes] == ["CENTRO B"]

    def test_una_fila_sin_nombre_de_zona_se_descarta(self) -> None:
        assert leer_mapeo([["", "CENTRO A", "1", "1", ""]]) == []

    def test_un_total_en_cero_no_divide_por_cero(self) -> None:
        assert leer_mapeo([["CENTRO", "CENTRO A", "0", "0", ""]])[0].peso == 0.0


class _TablaFalsa:
    """Lo mínimo de la interfaz de PostgREST para ver con qué filtros se consulta."""

    def __init__(self, filas: list[dict[str, object]], filtros: list[tuple[str, object]]) -> None:
        self._filas = filas
        self._filtros = filtros
        self._agotada = False

    def select(self, *_: object, **__: object) -> "_TablaFalsa":
        return self

    def order(self, *_: object, **__: object) -> "_TablaFalsa":
        return self

    def eq(self, columna: str, valor: object) -> "_TablaFalsa":
        self._filtros.append((columna, valor))
        return self

    def range(self, inicio: int, _fin: int) -> "_TablaFalsa":
        self._agotada = inicio > 0
        return self

    def execute(self) -> object:
        filas = [] if self._agotada else self._filas
        return type("Respuesta", (), {"data": filas, "count": len(filas)})()


class _ClienteFalso:
    def __init__(self, filas: list[dict[str, object]]) -> None:
        self._filas = filas
        self.filtros: list[tuple[str, object]] = []

    def table(self, _nombre: str) -> _TablaFalsa:
        return _TablaFalsa(self._filas, self.filtros)


class TestElRepertorioNoFiltraPorEstadoDeLaZona:
    """La herencia lee el repertorio de zonas YA desactivadas.

    Al aplicar la maestra nueva, las 124 zonas viejas quedaron en `activa = false`
    por no tener clientes, y son el único origen de la herencia. Un filtro por
    `activa` en la lectura del repertorio no daría error: devolvería menos filas y
    la herencia saldría vacía o incompleta en silencio. Estas pruebas están para
    que nadie agregue ese filtro sin que algo avise.
    """

    _FILA = {
        "dia_semana": _LUNES,
        "frecuencia": 18,
        "carros": {"numero": "3"},
        "zonas": {"nombre": "(CHIQUINQUIRA): CHIQUIN RUTA 1 NORTE"},
    }

    def _repositorio(self) -> tuple[object, _ClienteFalso]:
        from planeacion.infraestructura.adaptadores.salida.supabase.repositorio_carro_zonas import (
            RepositorioCarroZonasSupabase,
        )

        falso = _ClienteFalso([dict(self._FILA)])
        return RepositorioCarroZonasSupabase(cliente=falso), falso  # type: ignore[arg-type]

    def test_frecuencias_no_filtra_por_activa(self) -> None:
        repositorio, falso = self._repositorio()

        frecuencias = repositorio.frecuencias()  # type: ignore[attr-defined]

        assert [columna for columna, _ in falso.filtros if "activ" in columna] == []
        assert frecuencias == {ParRepertorio("3", "(CHIQUINQUIRA): CHIQUIN RUTA 1 NORTE", _LUNES): 18}

    def test_el_par_de_una_zona_inactiva_llega_a_la_herencia(self) -> None:
        """La prueba de punta a punta de lo anterior: el par leído de una zona
        apagada alcanza para que la zona nueva herede."""
        repositorio, _ = self._repositorio()
        nueva = "(CHIQUINQUIRA: CHIQUIN NORTE RUTA 3 - 4"
        origenes = [_origen(nueva, "(CHIQUINQUIRA): CHIQUIN RUTA 1 NORTE", 339, 339)]

        herencia = heredar(origenes, repositorio.frecuencias())  # type: ignore[attr-defined]

        assert herencia.pares == [ParRepertorio("3", nueva, _LUNES, frecuencia=18)]
