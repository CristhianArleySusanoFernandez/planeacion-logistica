"""`--desde-guardadas`: la siembra aprende de las planeaciones guardadas en el Paso 4.

Cuando la operación deje el Excel no habrá más `.xlsm` de dónde sembrar; lo que
quede es lo que la app guardó. Las reglas de deduplicación están acá y en el
docstring de `lecturas_desde_guardadas`.
"""

from datetime import date

from planeacion.application.dto.planeacion import PlaneacionGuardada
from planeacion.infraestructura.adaptadores.entrada.cli.sembrar_repertorio import (
    LecturaArchivo,
    contar_frecuencias,
    cruzar_pares,
    lecturas_desde_guardadas,
)

_PARES = (("18", "(TUNJA): NIEVES"), ("19", "(TUNJA): FLORIDA"), ("6", "COMFABOY"))


def _guardada(fecha: str, creada_en: str = "2026-11-13T10:00:00", pares=_PARES) -> PlaneacionGuardada:
    return PlaneacionGuardada(
        fecha=date.fromisoformat(fecha), dia_semana="martes", creada_en=creada_en, pares=pares
    )


def _xlsm(fecha: str) -> LecturaArchivo:
    return LecturaArchivo(f"DEL {fecha}.xlsm", ("martes",), 9, 9, (("18", "(TUNJA): NIEVES"),), fecha)


class TestDesdeGuardadas:
    def test_una_guardada_sola_entra_como_lectura_de_su_dia(self) -> None:
        usadas = lecturas_desde_guardadas([_guardada("2026-11-17")], [])

        [lectura] = usadas.lecturas
        assert lectura.archivo == "guardada:2026-11-17"
        assert lectura.dias == ("martes",) and lectura.fecha == "2026-11-17"
        assert lectura.pares == tuple(sorted(_PARES))
        assert lectura.facturas_bloque == lectura.facturas_planeacion  # cuadra: no hay bloque de ECOM
        assert contar_frecuencias([lectura])[("18", "(TUNJA): NIEVES", "martes")] == 1

    def test_con_xlsm_de_la_misma_fecha_gana_el_xlsm(self) -> None:
        usadas = lecturas_desde_guardadas([_guardada("2026-11-10")], [_xlsm("2026-11-10")])

        assert usadas.lecturas == []
        assert usadas.descartadas_por_xlsm == ["2026-11-10"]

    def test_dos_guardadas_de_la_misma_fecha_gana_la_mas_reciente(self) -> None:
        vieja = _guardada("2026-11-17", "2026-11-17T08:00:00", (("18", "(TUNJA): NIEVES"),))
        nueva = _guardada("2026-11-17", "2026-11-17T09:30:00", (("19", "(TUNJA): NIEVES"),))

        usadas = lecturas_desde_guardadas([nueva, vieja], [])

        [lectura] = usadas.lecturas
        assert lectura.pares == (("19", "(TUNJA): NIEVES"),)
        assert usadas.repetidas == ["2026-11-17"]

    def test_una_guardada_anterior_a_la_maestra_nueva_se_descarta(self) -> None:
        usadas = lecturas_desde_guardadas([_guardada("2026-07-09")], [])

        assert usadas.lecturas == [] and usadas.anteriores_a_la_maestra == ["2026-07-09"]

    def test_el_carro_nulo_no_llega_porque_el_adaptador_lo_filtra_y_la_zona_sin_par_no_cuenta(self) -> None:
        """El adaptador solo entrega pares con carro: una guardada sin ninguno es una lectura
        vacía, que el descarte de siembra atrapa como 'sin ningún par'."""
        usadas = lecturas_desde_guardadas([_guardada("2026-11-17", pares=())], [])

        [lectura] = usadas.lecturas
        assert lectura.pares == () and lectura.zonas == 0

    def test_las_especiales_se_saltan_en_el_cruce_como_con_los_xlsm(self) -> None:
        usadas = lecturas_desde_guardadas([_guardada("2026-11-17")], [])
        frecuencias = contar_frecuencias(usadas.lecturas)
        nombres_no_especiales = {"(TUNJA): NIEVES", "(TUNJA): FLORIDA"}  # COMFABOY es especial

        validos, _, desconocidas = cruzar_pares(set(frecuencias), {"18", "19", "6"}, nombres_no_especiales)

        assert {zona for _, zona, _ in validos} == nombres_no_especiales
        assert desconocidas == {"COMFABOY"}
