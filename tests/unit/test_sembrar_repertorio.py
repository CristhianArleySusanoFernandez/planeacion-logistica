"""Pruebas de la siembra del repertorio: lectura de la hoja PLANEACION, descarte
de archivos no confiables, conteo de frecuencias y cruce con la base."""

from collections import Counter
from pathlib import Path

import openpyxl

from planeacion.application.puertos.salida.repositorios import ParRepertorio
from planeacion.infraestructura.adaptadores.entrada.cli.sembrar_repertorio import (
    LecturaArchivo,
    contar_frecuencias,
    cruzar_pares,
    distribucion_de_frecuencias,
    minimo_de_zonas,
    motivo_de_descarte,
    zonas_que_quedarian_huerfanas,
)
from planeacion.infraestructura.adaptadores.salida.excel.lector_referencia import (
    LectorReferenciaExcel,
)


def _libro_con_planeacion(ruta: Path) -> None:
    libro = openpyxl.Workbook()
    hoja = libro.active
    assert hoja is not None
    hoja.title = "PLANEACION"
    hoja.append(["PLANEACION DEL DIA"])  # fila 1: título
    hoja.append([None, None, 1247, 143746644.81])  # fila 2: Promedio Vh
    hoja.append([None, "Ventas Totales", 1247])  # fila 3
    hoja.append(["CARROS", "CUADRANTE", "FACTURAS", "PESOS"])  # fila 4: encabezados
    hoja.append([1, "(CHIQUINQUIRA):   CHIQUIN RUTA  SUR 1", 40, 100.0])
    hoja.append([16, "(TUNJA):  ARCABUCO-MOTAVITA", 30, 90.0])
    hoja.append(["#N/D", "#N/D", 0, 0])  # cliente sin zona: no es un par real
    hoja.append([None, "(en blanco)", 0, 0])  # cierre del pivote viejo
    hoja.append([None, "Total general", 1247, 143746644.81])
    libro.save(ruta)


def test_leer_asignaciones_planeacion_filtra_lo_que_no_es_un_par(tmp_path: Path) -> None:
    ruta = tmp_path / "referencia.xlsx"
    _libro_con_planeacion(ruta)

    with LectorReferenciaExcel(ruta) as lector:
        pares = [(fila.carro, fila.zona) for fila in lector.leer_asignaciones_planeacion()]

    assert pares == [
        ("1", "(CHIQUINQUIRA):   CHIQUIN RUTA  SUR 1"),
        ("16", "(TUNJA):  ARCABUCO-MOTAVITA"),
    ]


def _lectura(
    archivo: str = "dia.xlsm",
    dias: tuple[str, ...] = ("jueves",),
    zonas: int = 70,
    facturas_bloque: int = 1000,
    facturas_planeacion: int = 1000,
) -> LecturaArchivo:
    return LecturaArchivo(
        archivo=archivo,
        dias=dias,
        facturas_bloque=facturas_bloque,
        facturas_planeacion=facturas_planeacion,
        pares=tuple(("3", f"ZONA {numero}") for numero in range(zonas)),
    )


class TestDescartes:
    def test_un_archivo_normal_se_usa(self) -> None:
        assert motivo_de_descarte(_lectura(), minimo_zonas=17) is None

    def test_se_descarta_el_que_cubre_dos_jornadas(self) -> None:
        """El reparto manual las cubre como un bloque único: no hay forma de decir
        a cuál pertenece cada zona, y atribuirlo a las dos inventaría evidencia."""
        motivo = motivo_de_descarte(_lectura(dias=("lunes", "martes")), minimo_zonas=17)

        assert motivo is not None
        assert "2 jornadas" in motivo and "lunes, martes" in motivo

    def test_se_descarta_el_que_no_cuadra_con_su_propio_bloque(self) -> None:
        """Mismo criterio que planeacion-validar: si el ECOM pegado no es el que se
        planeó, la hoja PLANEACION describe el reparto de otra entrada."""
        motivo = motivo_de_descarte(_lectura(facturas_bloque=2435, facturas_planeacion=2097), minimo_zonas=17)

        assert motivo is not None
        assert "2435" in motivo and "2097" in motivo

    def test_se_descarta_el_abandonado_a_medias(self) -> None:
        """El caso real: un archivo con 2 zonas contra las ~70 de un día normal,
        porque ese día se rehízo en otro archivo."""
        motivo = motivo_de_descarte(_lectura(zonas=2), minimo_zonas=17)

        assert motivo is not None
        assert "volumen anómalo" in motivo

    def test_se_descarta_el_que_no_tiene_fecha_legible(self) -> None:
        motivo = motivo_de_descarte(_lectura(dias=()), minimo_zonas=17)

        assert motivo is not None
        assert "ninguna fecha legible" in motivo

    def test_el_piso_de_volumen_sale_de_la_mediana_del_lote(self) -> None:
        """Relativo y no fijo: cuántas zonas tiene un día normal cambia con el
        negocio, y la mediana no se corre por los propios archivos anómalos."""
        lote = [_lectura(zonas=70) for _ in range(5)] + [_lectura(zonas=2)]

        assert minimo_de_zonas(lote) == 17  # 70 × 0.25

    def test_sin_archivos_el_piso_es_cero_y_no_revienta(self) -> None:
        assert minimo_de_zonas([]) == 0


class TestFrecuencias:
    def test_cuenta_una_vez_por_jornada_no_por_fila(self) -> None:
        """La unidad de observación es el archivo: si la hoja repite un par, sigue
        siendo una sola jornada en que ese carro hizo esa zona."""
        repetido = LecturaArchivo(
            archivo="a.xlsm",
            dias=("jueves",),
            facturas_bloque=1,
            facturas_planeacion=1,
            pares=(("3", "ZONA A"), ("3", "ZONA A"), ("4", "ZONA B")),
        )

        frecuencias = contar_frecuencias([repetido])

        assert frecuencias[("3", "ZONA A", "jueves")] == 1
        assert frecuencias[("4", "ZONA B", "jueves")] == 1

    def test_el_mismo_par_en_dias_distintos_no_se_suma(self) -> None:
        """Es la razón de ser de la migración 003: el jueves y el viernes son
        configuraciones distintas, no dos observaciones de la misma."""
        jueves = LecturaArchivo("a.xlsm", ("jueves",), 1, 1, (("12", "(TUNJA): ASIS"),))
        viernes = LecturaArchivo("b.xlsm", ("viernes",), 1, 1, (("13", "(TUNJA): ASIS"),))
        otro_jueves = LecturaArchivo("c.xlsm", ("jueves",), 1, 1, (("12", "(TUNJA): ASIS"),))

        frecuencias = contar_frecuencias([jueves, viernes, otro_jueves])

        assert frecuencias[("12", "(TUNJA): ASIS", "jueves")] == 2
        assert frecuencias[("13", "(TUNJA): ASIS", "viernes")] == 1

    def test_la_distribucion_agrupa_los_de_tres_o_mas(self) -> None:
        frecuencias: Counter[tuple[str, str, str]] = Counter(
            {
                ("3", "A", "lunes"): 1,
                ("3", "B", "lunes"): 2,
                ("3", "C", "lunes"): 7,
                ("4", "D", "lunes"): 3,
            }
        )

        assert distribucion_de_frecuencias(frecuencias) == {"1 vez": 1, "2 veces": 1, "3+ veces": 2}


class TestCruzarPares:
    def test_separa_carros_y_zonas_desconocidos(self) -> None:
        pares = {
            ("1", "(TUNJA): NIEVES", "lunes"),
            ("18", "RAQUIRA", "lunes"),
            ("99", "(TUNJA): NIEVES", "lunes"),  # carro que no está en la base
            ("1", "ZONA FANTASMA", "lunes"),  # zona que no casa con zonas.nombre
        }

        validos, carros_desconocidos, zonas_desconocidas = cruzar_pares(
            pares, numeros_carros={"1", "18"}, nombres_zonas={"(TUNJA): NIEVES", "RAQUIRA"}
        )

        assert validos == {("1", "(TUNJA): NIEVES", "lunes"), ("18", "RAQUIRA", "lunes")}
        assert set(carros_desconocidos) == {"99"}
        assert zonas_desconocidas == {"ZONA FANTASMA"}

    def test_un_carro_desconocido_reporta_en_que_dias_trabajo(self) -> None:
        """Los refuerzos aparecen sobre todo los sábados: saber en qué días
        trabajaron es lo que permite decidir si darlos de alta."""
        pares = {
            ("21", "ZONA A", "sabado"),
            ("21", "ZONA B", "sabado"),
            ("21", "ZONA C", "lunes"),
            ("23", "ZONA A", "sabado"),
        }

        _, carros_desconocidos, _ = cruzar_pares(pares, numeros_carros=set(), nombres_zonas={"ZONA A"})

        assert carros_desconocidos["21"] == {"sabado", "lunes"}
        assert carros_desconocidos["23"] == {"sabado"}


class TestBorrarFrecuenciaCero:
    def test_avisa_que_zonas_pierden_su_ultimo_carro(self) -> None:
        """El daño colateral del borrado: una zona cuyos pares son todos
        configuración a mano se queda sin nadie que la reparta."""
        frecuencias = {
            ParRepertorio("3", "OBSERVADA", "lunes", 4),
            ParRepertorio("3", "OBSERVADA", "martes", 0),
            ParRepertorio("5", "SOLO A MANO", "lunes", 0),
            ParRepertorio("5", "SOLO A MANO", "martes", 0),
        }

        huerfanas = zonas_que_quedarian_huerfanas({par: par.frecuencia for par in frecuencias})

        assert huerfanas == ["SOLO A MANO"]

    def test_una_zona_observada_algun_dia_sobrevive(self) -> None:
        """Pierde los días sin evidencia, pero conserva el carro donde sí la hubo:
        justamente el efecto que se busca con la dimensión del día."""
        frecuencias = {ParRepertorio("3", "ZONA", "sabado", 2), ParRepertorio("3", "ZONA", "lunes", 0)}

        assert zonas_que_quedarian_huerfanas({par: par.frecuencia for par in frecuencias}) == []

    def test_sin_repertorio_no_hay_huerfanas(self) -> None:
        assert zonas_que_quedarian_huerfanas({}) == []
