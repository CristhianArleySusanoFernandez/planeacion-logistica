"""Pruebas del parseo de zonas: prefijo → municipio, SUR/NORTE, normalización."""

import pytest

from planeacion.domain.errores import ZonaInvalida
from planeacion.domain.modelo import MUNICIPIO_OTROS, ReglaChiquinquira
from planeacion.domain.servicios.parseo_zonas import (
    crear_zona,
    detectar_regla_chiquinquira,
    normalizar_nombre_zona,
    parsear_municipio,
)


class TestNormalizarNombreZona:
    def test_colapsa_espacios_multiples(self) -> None:
        assert normalizar_nombre_zona("(BARBOSA):   BARBOSA-PUENTE") == "(BARBOSA): BARBOSA-PUENTE"

    def test_recorta_extremos(self) -> None:
        assert normalizar_nombre_zona("  VILLA DE LEYVA  ") == "VILLA DE LEYVA"

    def test_variantes_de_espaciado_producen_la_misma_clave(self) -> None:
        assert normalizar_nombre_zona("(BARBOSA):  BARBOSA-CITE") == normalizar_nombre_zona(
            "(BARBOSA):   BARBOSA-CITE"
        )

    def test_es_idempotente(self) -> None:
        for crudo in ("(BARBOSA):   BARBOSA-PUENTE", "  VILLA DE LEYVA  ", "(TUNJA): RUTA CENTRO 1"):
            una_vez = normalizar_nombre_zona(crudo)
            assert normalizar_nombre_zona(una_vez) == una_vez


class TestParsearMunicipio:
    def test_prefijo_normal(self) -> None:
        assert parsear_municipio("(BARBOSA): BARBOSA-PUENTE") == "BARBOSA"

    def test_prefijo_tunja(self) -> None:
        assert parsear_municipio("(TUNJA): RUTA CENTRO 1") == "TUNJA"

    def test_malformado_sin_cerrar_parentesis(self) -> None:
        # Caso real de la MAESTRA: "(CHIQUINQUIRA:   CHIQUIN NORTE RUTA 3"
        assert parsear_municipio("(CHIQUINQUIRA: CHIQUIN NORTE RUTA 3") == "CHIQUINQUIRA"

    def test_sin_prefijo_es_otros(self) -> None:
        assert parsear_municipio("VILLA DE LEYVA") == MUNICIPIO_OTROS

    def test_parentesis_no_inicial_es_otros(self) -> None:
        # El municipio solo cuenta como prefijo: "PARAISO (TUNJA)" no es de TUNJA.
        assert parsear_municipio("PARAISO (TUNJA)") == MUNICIPIO_OTROS


class TestDetectarReglaChiquinquira:
    def test_sur(self) -> None:
        nombre = "(CHIQUINQUIRA): SUSA - SIMIJACA RUTA SUR 1"
        assert detectar_regla_chiquinquira(nombre, "CHIQUINQUIRA") is ReglaChiquinquira.SUR

    def test_norte(self) -> None:
        nombre = "(CHIQUINQUIRA): CHIQUIN RUTA 1 NORTE"
        assert detectar_regla_chiquinquira(nombre, "CHIQUINQUIRA") is ReglaChiquinquira.NORTE

    def test_surinema_no_confunde(self) -> None:
        # "SURINEMA" y "PRADOSUR" no deben contar como SUR; el token real es "RUTA SUR 4".
        nombre = "(CHIQUINQUIRA): SURINEMA-PRADOSUR-POLO-COUNTRY-BOYACA ALTO Y BAJO (CHIQUI) RUTA SUR 4"
        assert detectar_regla_chiquinquira(nombre, "CHIQUINQUIRA") is ReglaChiquinquira.SUR

    def test_sin_token_es_none(self) -> None:
        assert detectar_regla_chiquinquira("(CHIQUINQUIRA): CENTRO", "CHIQUINQUIRA") is None

    def test_otro_municipio_es_none(self) -> None:
        assert detectar_regla_chiquinquira("(TUNJA): RUTA SUR", "TUNJA") is None


class TestCrearZona:
    def test_zona_completa(self) -> None:
        zona = crear_zona("(CHIQUINQUIRA:   CHIQUIN NORTE RUTA 3")
        assert zona.nombre == "(CHIQUINQUIRA: CHIQUIN NORTE RUTA 3"
        assert zona.municipio.nombre == "CHIQUINQUIRA"
        assert zona.regla_chiquinquira is ReglaChiquinquira.NORTE
        assert zona.activa

    def test_zona_viajera_va_a_otros(self) -> None:
        zona = crear_zona("RUTA MUZO")
        assert zona.municipio.nombre == MUNICIPIO_OTROS
        assert zona.regla_chiquinquira is None

    def test_nombre_vacio_lanza_error(self) -> None:
        with pytest.raises(ZonaInvalida):
            crear_zona("   ")
