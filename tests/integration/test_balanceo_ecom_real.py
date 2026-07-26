"""Validación del balanceador con el ECOM real (sin asignación previa).

El umbral de CV < 25% solo se exige donde es estructuralmente alcanzable:
- CHIQUINQUIRA: todas sus zonas traen la regla dura SUR/NORTE, quedan fijadas a
  los dos primeros carros del pool y no hay nada que la heurística pueda mover.
- OTROS: son rutas viajeras geográficas; VENTAQUEMADA-VUELTA AL MUNDO trae 78
  clientes ella sola (más que la media de ~43 por carro con 7 carros), así que
  ningún reparto puede bajar el CV de clientes del ~31%. En la planeación real
  de Rudy esas rutas tampoco están balanceadas (MIRAFLORES o FLORIAN van solas).
En esos dos municipios se verifica conservación y que el costo no empeore.
"""

from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

RUTA_ECOM = Path("datos/pedidos24-26Junio.xlsx")
_MUNICIPIOS_CON_UMBRAL = {"BARBOSA", "TUNJA"}
_CV_MAXIMO = 0.25
_TOLERANCIA_PESOS = Decimal("0.01")


def _hay_credenciales() -> bool:
    try:
        from planeacion.config.settings import Settings

        Settings()
        return True
    except ValidationError:
        return False


@pytest.mark.integration
@pytest.mark.skipif(
    not (_hay_credenciales() and RUTA_ECOM.exists()),
    reason="sin credenciales de Supabase o sin datos/pedidos24-26Junio.xlsx",
)
def test_balanceo_del_ecom_real_mejora_y_conserva() -> None:
    from planeacion.config.contenedor import (
        crear_contenedor,
        crear_generar_pivote,
        crear_generar_planeacion,
    )

    contenedor = crear_contenedor()
    pivote = crear_generar_pivote(contenedor).ejecutar(RUTA_ECOM)
    planeacion = crear_generar_planeacion(contenedor).ejecutar(RUTA_ECOM)
    resultado = planeacion.resultado

    # Conservación: el balanceador mueve zonas pero no pierde ni inventa datos.
    # Con el repertorio sembrado, una zona viajera puede balancearse en el pool
    # de otro municipio (ej. RAQUIRA en Chiquinquirá), así que se verifica por
    # ZONA (cada una aparece exactamente una vez, con sus mismos números), no
    # por municipio de la zona.
    vistas: dict[str, tuple[int, Decimal]] = {}
    for cargas in resultado.cargas_por_municipio.values():
        for carga in cargas:
            for asignada in carga.zonas:
                assert asignada.zona.nombre not in vistas, f"duplicada: {asignada.zona.nombre}"
                vistas[asignada.zona.nombre] = (asignada.clientes, asignada.pesos)
    for suelta in resultado.zonas_sin_carro:
        assert suelta.zona.nombre not in vistas, f"duplicada: {suelta.zona.nombre}"
        vistas[suelta.zona.nombre] = (suelta.clientes, suelta.pesos)

    esperado = {zona.zona: (zona.clientes, zona.pesos) for zona in pivote.zonas}
    assert vistas.keys() == esperado.keys()
    for nombre, (clientes_esperados, pesos_esperados) in esperado.items():
        clientes, pesos = vistas[nombre]
        assert clientes == clientes_esperados, nombre
        assert abs(pesos - pesos_esperados) <= _TOLERANCIA_PESOS, nombre

    # Mejora: el COSTO PONDERADO (lo que la heurística minimiza) nunca empeora.
    # Un CV individual puede subir si el otro baja más (p.ej. sacrificar 2 puntos
    # de clientes para bajar 14 de pesos): eso es una mejora, no una regresión.
    for municipio, finales in resultado.metricas_finales.items():
        iniciales = resultado.metricas_iniciales[municipio]
        costo_inicial = 0.5 * iniciales.cv_clientes + 0.5 * iniciales.cv_pesos
        costo_final = 0.5 * finales.cv_clientes + 0.5 * finales.cv_pesos
        assert costo_final <= costo_inicial + 1e-9, municipio
        if municipio not in _MUNICIPIOS_CON_UMBRAL:
            continue
        assert finales.cv_clientes < _CV_MAXIMO, f"{municipio}: cv clientes {finales.cv_clientes:.1%}"
        assert finales.cv_pesos < _CV_MAXIMO, f"{municipio}: cv pesos {finales.cv_pesos:.1%}"
