"""Pruebas de la auditoría y la fusión de zonas duplicadas por normalización."""

from planeacion.domain.modelo import Municipio, Zona
from planeacion.domain.servicios.auditoria_zonas import (
    GrupoDuplicado,
    ReferenciasMovidas,
    VarianteZona,
    agrupar_duplicados,
    planear_fusion,
)


def _zona(nombre: str, municipio: str = "BARBOSA") -> Zona:
    return Zona(nombre=nombre, municipio=Municipio(nombre=municipio))


class TestAgruparDuplicados:
    def test_detecta_variantes_de_espaciado(self) -> None:
        zonas = [
            _zona("(BARBOSA):   BARBOSA-PUENTE"),
            _zona("(BARBOSA): BARBOSA-PUENTE"),
            _zona("(BARBOSA): BARBOSA-CITE"),  # sin duplicado
        ]
        grupos = agrupar_duplicados(zonas, {})
        assert grupos == [
            GrupoDuplicado(
                clave_normalizada="(BARBOSA): BARBOSA-PUENTE",
                variantes=(
                    VarianteZona("(BARBOSA):   BARBOSA-PUENTE", 0),
                    VarianteZona("(BARBOSA): BARBOSA-PUENTE", 0),
                ),
            )
        ]

    def test_sin_duplicados_no_reporta_nada(self) -> None:
        zonas = [_zona("(BARBOSA): BARBOSA-CITE"), _zona("(TUNJA): RUTA CENTRO 1", "TUNJA")]
        assert agrupar_duplicados(zonas, {}) == []

    def test_incluye_el_conteo_de_clientes_por_variante(self) -> None:
        zonas = [_zona("(BARBOSA):   CITE"), _zona("(BARBOSA): CITE")]
        conteo = {"(BARBOSA):   CITE": 3, "(BARBOSA): CITE": 40}
        [grupo] = agrupar_duplicados(zonas, conteo)
        por_nombre = {v.nombre: v.clientes for v in grupo.variantes}
        assert por_nombre == {"(BARBOSA):   CITE": 3, "(BARBOSA): CITE": 40}

    def test_ordena_los_grupos_con_mas_clientes_primero(self) -> None:
        zonas = [
            _zona("(BARBOSA):   A"),
            _zona("(BARBOSA): A"),
            _zona("(BARBOSA):   B"),
            _zona("(BARBOSA): B"),
        ]
        conteo = {"(BARBOSA):   A": 1, "(BARBOSA): A": 1, "(BARBOSA):   B": 50, "(BARBOSA): B": 50}
        grupos = agrupar_duplicados(zonas, conteo)
        assert [g.clave_normalizada for g in grupos] == ["(BARBOSA): B", "(BARBOSA): A"]


def _grupo(*variantes: tuple[str, int]) -> GrupoDuplicado:
    return GrupoDuplicado(
        clave_normalizada="(BARBOSA): CITE",
        variantes=tuple(VarianteZona(nombre, clientes) for nombre, clientes in variantes),
    )


class TestPlanearFusion:
    def test_gana_la_variante_con_mas_clientes(self) -> None:
        plan = planear_fusion(_grupo(("(BARBOSA):   CITE", 40), ("(BARBOSA): CITE", 3)))
        assert plan.canonica == "(BARBOSA):   CITE"
        assert plan.variantes == ("(BARBOSA): CITE",)

    def test_en_empate_gana_la_mas_corta(self) -> None:
        # Mismo número de clientes: sobrevive la escritura limpia, sin espacios de más.
        plan = planear_fusion(_grupo(("(BARBOSA):   CITE", 5), ("(BARBOSA): CITE", 5)))
        assert plan.canonica == "(BARBOSA): CITE"
        assert plan.variantes == ("(BARBOSA):   CITE",)

    def test_en_empate_total_es_determinista_por_orden_alfabetico(self) -> None:
        plan = planear_fusion(_grupo(("(BARBOSA): B", 0), ("(BARBOSA): A", 0)))
        assert plan.canonica == "(BARBOSA): A"

    def test_absorbe_todas_las_demas_variantes(self) -> None:
        plan = planear_fusion(
            _grupo(("(BARBOSA): CITE", 9), ("(BARBOSA):  CITE", 2), ("(BARBOSA):   CITE", 1))
        )
        assert plan.canonica == "(BARBOSA): CITE"
        assert set(plan.variantes) == {"(BARBOSA):  CITE", "(BARBOSA):   CITE"}


class TestReferenciasMovidas:
    def test_total_suma_las_cuatro_tablas(self) -> None:
        movidas = ReferenciasMovidas(clientes=3, repertorio=2, overrides=1, planeaciones=4)
        assert movidas.total == 10

    def test_se_acumulan_sumando(self) -> None:
        acumulado = ReferenciasMovidas(clientes=3) + ReferenciasMovidas(clientes=2, overrides=1)
        assert acumulado == ReferenciasMovidas(clientes=5, overrides=1)
