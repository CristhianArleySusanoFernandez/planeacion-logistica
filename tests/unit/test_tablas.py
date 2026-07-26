"""Pruebas de los helpers puros de Configuración: filtro de texto y diff de filas."""

from planeacion.infraestructura.adaptadores.entrada.web.tablas import calcular_diff, filtrar_filas

FILAS = [
    {"nombre": "(TUNJA): NIEVES", "municipio": "TUNJA", "activa": True, "carros": "13, 14"},
    {"nombre": "(BARBOSA): CENTRO", "municipio": "BARBOSA", "activa": True, "carros": "⚠ sin carro"},
    {"nombre": "RAQUIRA", "municipio": "OTROS", "activa": False, "carros": "2"},
]


def test_filtrar_es_parcial_y_case_insensitive() -> None:
    assert filtrar_filas(FILAS, "tunja") == [FILAS[0]]
    assert filtrar_filas(FILAS, "  RaQuIrA ") == [FILAS[2]]


def test_filtrar_sin_texto_devuelve_todo() -> None:
    assert filtrar_filas(FILAS, "") == FILAS
    assert filtrar_filas(FILAS, "   ") == FILAS


def test_filtrar_aplica_a_columnas_calculadas_como_sin_carro() -> None:
    assert filtrar_filas(FILAS, "sin carro") == [FILAS[1]]


def test_filtrar_no_casa_contra_columnas_no_textuales() -> None:
    # "True" solo existe como bool: no debe casar.
    assert filtrar_filas(FILAS, "true") == []


def test_diff_detecta_nuevas_editadas_y_eliminadas() -> None:
    originales = [
        {"numero": "1", "conductor": "FABIAN"},
        {"numero": "2", "conductor": "JUAN PABLO"},
        {"numero": "3", "conductor": "DAVID"},
    ]
    editadas = [
        {"numero": "1", "conductor": "FABIAN"},  # intacta
        {"numero": "2", "conductor": "JUAN P. CASTRO"},  # editada
        {"numero": "19", "conductor": "NUEVO"},  # nueva (y la 3 desapareció)
    ]

    diff = calcular_diff(originales, editadas, "numero")

    assert diff.nuevas == [{"numero": "19", "conductor": "NUEVO"}]
    assert diff.editadas == [{"numero": "2", "conductor": "JUAN P. CASTRO"}]
    assert diff.eliminadas == ["3"]
    assert diff.invalidas == []


def test_diff_fila_sin_llave_con_datos_es_invalida_y_vacia_se_ignora() -> None:
    diff = calcular_diff(
        originales=[],
        editadas=[
            {"numero": None, "conductor": "SIN NUMERO"},  # inválida
            {"numero": "", "conductor": None},  # fila vacía del editor: se ignora
        ],
        clave="numero",
    )

    assert diff.invalidas == [{"numero": None, "conductor": "SIN NUMERO"}]
    assert diff.nuevas == [] and diff.editadas == [] and diff.eliminadas == []


def test_diff_renombrar_la_llave_es_alta_mas_baja() -> None:
    diff = calcular_diff(
        originales=[{"nombre": "ZONA VIEJA", "activa": True}],
        editadas=[{"nombre": "ZONA NUEVA", "activa": True}],
        clave="nombre",
    )

    assert [f["nombre"] for f in diff.nuevas] == ["ZONA NUEVA"]
    assert diff.eliminadas == ["ZONA VIEJA"]


def test_diff_contra_visibles_no_elimina_lo_oculto_por_el_filtro() -> None:
    todas = FILAS
    visibles = filtrar_filas(todas, "tunja")  # solo NIEVES a la vista

    diff = calcular_diff(visibles, visibles, "nombre")

    # Las otras dos filas están ocultas, no eliminadas.
    assert diff.eliminadas == []
