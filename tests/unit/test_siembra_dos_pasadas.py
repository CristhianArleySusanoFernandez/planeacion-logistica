"""La siembra en dos pasadas: el CSV liviano de cada .xlsm y la verificación en memoria.

Cada .xlsm pesa ~37 MB y abrirlo cuesta más de 1 GB; con 13 archivos en un solo
proceso el portátil de 8 GB se queda sin memoria. Por eso cada archivo se lee en
un subproceso que deja un CSV con lo único que la siembra necesita, y
`--solo-verificar` simula siembra + herencia sin tocar la base.
"""

from pathlib import Path

from planeacion.application.puertos.salida.repositorios import ParRepertorio
from planeacion.domain.modelo import Municipio, Zona
from planeacion.infraestructura.adaptadores.entrada.cli.herencia import Origen
from planeacion.infraestructura.adaptadores.entrada.cli.sembrar_repertorio import (
    LecturaArchivo,
    contar_frecuencias,
    costumbres_por_periodo,
    escribir_lectura,
    leer_archivos,
    leer_lectura,
    verificar_siembra,
)

_BARBOSA = Municipio("BARBOSA")
_LUNES = LecturaArchivo(
    archivo="DEL 20-10.xlsm",
    dias=("lunes",),
    facturas_bloque=10,
    facturas_planeacion=10,
    pares=(("6", "(BARBOSA): MONIQUIRA"), ("7", "(BARBOSA): CENTRO")),
    fecha="2026-10-20",
)
_LUNES_NOV = LecturaArchivo(
    archivo="DEL 09-11.xlsm",
    dias=("lunes",),
    facturas_bloque=12,
    facturas_planeacion=12,
    pares=(("7", "(BARBOSA): MONIQUIRA"), ("6", "(BARBOSA): CENTRO"), ("6", "(BARBOSA): GUEPSA")),
    fecha="2026-11-09",
)


class TestElCsvLiviano:
    def test_ida_y_vuelta_conserva_todo(self, tmp_path: Path) -> None:
        ruta = tmp_path / "lecturas" / "DEL 20-10.csv"

        escribir_lectura(_LUNES, ruta)

        assert leer_lectura(ruta) == _LUNES

    def test_una_lectura_vieja_sin_fecha_se_lee_con_fecha_vacia(self, tmp_path: Path) -> None:
        ruta = tmp_path / "l.csv"
        ruta.write_text(
            "archivo,dias,facturas_bloque,facturas_planeacion,fecha\nX.xlsm,martes,3,3,\ncarro,zona\n1,A\n",
            encoding="utf-8",
        )

        lectura = leer_lectura(ruta)

        assert lectura.fecha == "" and lectura.dias == ("martes",) and lectura.pares == (("1", "A"),)

    def test_el_csv_ya_extraido_se_reutiliza_sin_abrir_el_xlsm(self, tmp_path: Path) -> None:
        """Si el CSV es más nuevo que el .xlsm, no hay subproceso: el .xlsm ni se toca."""
        xlsm = tmp_path / "DEL 20-10.xlsm"
        xlsm.write_bytes(b"no es un excel de verdad")
        escribir_lectura(_LUNES, tmp_path / "lecturas" / "DEL 20-10.csv")

        lecturas = leer_archivos([xlsm], tmp_path / "lecturas")

        assert lecturas == [_LUNES]


class TestVerificarSiembra:
    _ZONAS = [
        Zona(nombre="(BARBOSA): MONIQUIRA", municipio=_BARBOSA),
        Zona(nombre="(BARBOSA): CENTRO", municipio=_BARBOSA),
        Zona(nombre="(BARBOSA): GUEPSA", municipio=_BARBOSA),
        Zona(nombre="(BARBOSA): VELEZ", municipio=_BARBOSA),  # activa, con pedidos, sin par
        Zona(nombre="(BARBOSA): VIEJA", municipio=_BARBOSA, activa=False),
        Zona(nombre="COMFABOY", municipio=_BARBOSA, especial=True),
    ]

    def test_cuenta_sembrados_heredados_y_lo_que_queda_sin_par(self) -> None:
        martes = LecturaArchivo(
            "DEL 21-10.xlsm", ("martes",), 5, 5, (("6", "(BARBOSA): VELEZ"), ("6", "COMFABOY")), "2026-10-21"
        )
        usables = [_LUNES, _LUNES_NOV, martes]
        frecuencias = contar_frecuencias(usables)
        # VELEZ y COMFABOY no se siembran (una no tiene par válido, la otra es especial)
        validos = {trio for trio in frecuencias if trio[1] not in {"(BARBOSA): VELEZ", "COMFABOY"}}
        # GUEPSA hereda el martes de VIEJA (que ese día iba en la 5); el lunes ya tiene par y se respeta
        origenes = [Origen("(BARBOSA): GUEPSA", "(BARBOSA): VIEJA", 10, 10)]
        origen = {
            ParRepertorio("5", "(BARBOSA): VIEJA", "martes", 4): 4,
            ParRepertorio("5", "(BARBOSA): VIEJA", "lunes", 4): 4,
        }

        v = verificar_siembra(usables, validos, frecuencias, self._ZONAS, origenes, origen)

        assert len(v.sembrados) == 5  # MONIQUIRA 6 y 7, CENTRO 7 y 6, GUEPSA 6 (todas lunes)
        assert v.heredados == [ParRepertorio("5", "(BARBOSA): GUEPSA", "martes", 4)]
        assert v.por_dia()[0] == ("lunes", 5, 0) and v.por_dia()[1] == ("martes", 0, 1)
        assert v.sin_par_con_pedidos == [("martes", "(BARBOSA): VELEZ", "DEL 21-10.xlsm")]
        assert v.sin_ningun_par == ["(BARBOSA): VELEZ"]
        # lunes: MONIQUIRA y CENTRO tienen 2 rutas; GUEPSA una ruta vista 1 vez.
        # martes: GUEPSA heredada con frecuencia 4, una sola ruta.
        assert (v.con_alternativa, v.candado_una_vez, v.candado_dos_o_mas) == (2, 1, 1)


class TestCostumbresPorPeriodo:
    def test_separa_lo_visto_antes_y_despues_del_corte(self) -> None:
        costumbres = costumbres_por_periodo([_LUNES, _LUNES_NOV], "2026-11-01", {"6", "7"})

        assert costumbres[("(BARBOSA): MONIQUIRA", "6")] == (1, 0)
        assert costumbres[("(BARBOSA): MONIQUIRA", "7")] == (0, 1)
        assert costumbres[("(BARBOSA): GUEPSA", "6")] == (0, 1)
        assert ("(BARBOSA): CENTRO", "5") not in costumbres

    def test_solo_cuenta_las_rutas_pedidas(self) -> None:
        assert costumbres_por_periodo([_LUNES], "2026-11-01", {"7"}) == {("(BARBOSA): CENTRO", "7"): (1, 0)}
