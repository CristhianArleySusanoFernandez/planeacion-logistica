"""Pruebas de la lógica pura de la matriz de repertorios (zonas × carros)."""

from planeacion.domain.modelo import Carro, Municipio, Zona
from planeacion.infraestructura.adaptadores.entrada.web.repertorio_matriz import (
    TODOS,
    CambioCelda,
    FiltroMatriz,
    aplicar_cambios,
    cambios_desde_edicion,
    carros_visibles,
    contar_carros_de_zona,
    contar_sin_carro,
    zonas_visibles,
)


def _zona(nombre: str, municipio: str) -> Zona:
    return Zona(nombre=nombre, municipio=Municipio(nombre=municipio))


def _carro(numero: str, municipio: str | None, activo: bool = True) -> Carro:
    return Carro(
        numero=numero,
        municipio=Municipio(nombre=municipio) if municipio else None,
        activo=activo,
    )


_ZONAS = [
    _zona("(BARBOSA):  CITE", "BARBOSA"),
    _zona("(BARBOSA):  VÉLEZ", "BARBOSA"),  # con acento, para la búsqueda
    _zona("(CHIQUINQUIRA):  SUR 1", "CHIQUINQUIRA"),
    _zona("RAQUIRA", "OTROS"),  # viajera atendida por un carro de Chiquinquirá
    _zona("RUTA MUZO", "OTROS"),  # huérfana: nadie la atiende
]

_CARROS = [
    _carro("3", "BARBOSA"),
    _carro("4", "BARBOSA"),
    _carro("2", "CHIQUINQUIRA"),
    _carro("9", "OTROS"),
    _carro("18", "BARBOSA", activo=False),  # inactivo: nunca es columna
]

_REPERTORIO = {
    "3": {"(BARBOSA):  CITE"},
    "2": {"(CHIQUINQUIRA):  SUR 1", "RAQUIRA"},
    "9": {"RAQUIRA"},
}


class TestZonasVisibles:
    def test_filtra_por_municipio_y_ordena_alfabetico(self) -> None:
        filas = zonas_visibles(_ZONAS, _REPERTORIO, FiltroMatriz(municipio="BARBOSA"))
        assert [z.nombre for z in filas] == ["(BARBOSA):  CITE", "(BARBOSA):  VÉLEZ"]

    def test_todos_incluye_todo_ordenado_por_municipio(self) -> None:
        filas = zonas_visibles(_ZONAS, _REPERTORIO, FiltroMatriz(municipio=TODOS))
        assert len(filas) == 5
        assert [z.municipio.nombre for z in filas] == sorted(z.municipio.nombre for z in filas)

    def test_solo_sin_carro_deja_las_huerfanas(self) -> None:
        filas = zonas_visibles(_ZONAS, _REPERTORIO, FiltroMatriz(municipio=TODOS, solo_sin_carro=True))
        # VÉLEZ y RUTA MUZO no aparecen en ningún repertorio.
        assert [z.nombre for z in filas] == ["(BARBOSA):  VÉLEZ", "RUTA MUZO"]

    def test_busqueda_sin_acentos(self) -> None:
        filas = zonas_visibles(_ZONAS, _REPERTORIO, FiltroMatriz(municipio=TODOS, texto="velez"))
        assert [z.nombre for z in filas] == ["(BARBOSA):  VÉLEZ"]

    def test_los_filtros_se_combinan(self) -> None:
        filtro = FiltroMatriz(municipio="OTROS", solo_sin_carro=True, texto="muzo")
        filas = zonas_visibles(_ZONAS, _REPERTORIO, filtro)
        assert [z.nombre for z in filas] == ["RUTA MUZO"]


class TestCarrosVisibles:
    def test_municipio_incluye_los_cruzados_que_atienden_una_fila(self) -> None:
        filas = [_zona("RAQUIRA", "OTROS"), _zona("RUTA MUZO", "OTROS")]
        columnas = carros_visibles(_CARROS, filas, _REPERTORIO, "OTROS")
        # El 9 es propio de OTROS; el 2 (Chiquinquirá) entra porque atiende RAQUIRA.
        assert [c.numero for c in columnas] == ["9", "2"]

    def test_sin_zonas_cruzadas_solo_los_propios(self) -> None:
        filas = [_zona("(BARBOSA):  CITE", "BARBOSA")]
        columnas = carros_visibles(_CARROS, filas, _REPERTORIO, "BARBOSA")
        assert [c.numero for c in columnas] == ["3", "4"]

    def test_todos_trae_los_activos_ordenados(self) -> None:
        columnas = carros_visibles(_CARROS, _ZONAS, _REPERTORIO, TODOS)
        assert [c.numero for c in columnas] == ["2", "3", "4", "9"]

    def test_el_inactivo_nunca_aparece(self) -> None:
        columnas = carros_visibles(_CARROS, _ZONAS, _REPERTORIO, "BARBOSA")
        assert "18" not in [c.numero for c in columnas]


class TestContadores:
    def test_contar_carros_de_zona(self) -> None:
        assert contar_carros_de_zona("RAQUIRA", _REPERTORIO) == 2
        assert contar_carros_de_zona("(BARBOSA):  CITE", _REPERTORIO) == 1
        assert contar_carros_de_zona("RUTA MUZO", _REPERTORIO) == 0

    def test_contar_sin_carro(self) -> None:
        assert contar_sin_carro(_ZONAS, _REPERTORIO) == (2, 5)
        assert contar_sin_carro(_ZONAS, {"3": {z.nombre for z in _ZONAS}}) == (0, 5)


class TestCambiosDesdeEdicion:
    _ORDEN = ["(BARBOSA):  CITE", "(BARBOSA):  VÉLEZ"]
    _NUMEROS = {"3", "4"}

    def test_traduce_marcado_y_desmarcado(self) -> None:
        editadas = {0: {"3": True}, 1: {"4": False}}
        assert cambios_desde_edicion(editadas, self._ORDEN, self._NUMEROS) == [
            CambioCelda("3", "(BARBOSA):  CITE", True),
            CambioCelda("4", "(BARBOSA):  VÉLEZ", False),
        ]

    def test_ignora_columnas_que_no_son_de_carro(self) -> None:
        editadas = {0: {"n_carros": 7, "zona": "otra", "3": True}}
        assert cambios_desde_edicion(editadas, self._ORDEN, self._NUMEROS) == [
            CambioCelda("3", "(BARBOSA):  CITE", True)
        ]

    def test_ignora_indices_fuera_de_la_vista(self) -> None:
        assert cambios_desde_edicion({5: {"3": True}}, self._ORDEN, self._NUMEROS) == []


class _RepoFalso:
    def __init__(self, falla_en: tuple[str, str] | None = None) -> None:
        self.asignados: list[tuple[str, str]] = []
        self.quitados: list[tuple[str, str]] = []
        self._falla_en = falla_en

    def _verificar(self, numero: str, zona: str) -> None:
        if (numero, zona) == self._falla_en:
            raise ConnectionError("sin red")

    def asignar(self, numero_carro: str, nombre_zona: str) -> None:
        self._verificar(numero_carro, nombre_zona)
        self.asignados.append((numero_carro, nombre_zona))

    def quitar(self, numero_carro: str, nombre_zona: str) -> None:
        self._verificar(numero_carro, nombre_zona)
        self.quitados.append((numero_carro, nombre_zona))


class TestAplicarCambios:
    def test_marcar_asigna_y_desmarcar_quita(self) -> None:
        repo = _RepoFalso()
        errores = aplicar_cambios(
            repo,  # type: ignore[arg-type]  # doble estructural del Protocol
            [CambioCelda("3", "ZONA A", True), CambioCelda("4", "ZONA B", False)],
        )
        assert errores == []
        assert repo.asignados == [("3", "ZONA A")]
        assert repo.quitados == [("4", "ZONA B")]

    def test_un_fallo_se_reporta_y_no_frena_el_resto(self) -> None:
        repo = _RepoFalso(falla_en=("3", "ZONA A"))
        errores = aplicar_cambios(
            repo,  # type: ignore[arg-type]
            [CambioCelda("3", "ZONA A", True), CambioCelda("4", "ZONA B", True)],
        )
        assert len(errores) == 1
        assert "ZONA A" in errores[0] and "carro 3" in errores[0]
        assert repo.asignados == [("4", "ZONA B")]
