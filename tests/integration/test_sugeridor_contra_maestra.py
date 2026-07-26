"""Validación del SugeridorDeZona con la maestra real (leave-one-out).

El ECOM de referencia no trae clientes #N/D (la maestra los cubre todos), así
que la calidad del sugeridor se mide de otra forma: se aparta una muestra de
clientes existentes, se construye el sugeridor con el RESTO de la maestra y se
verifica que a la muestra le sugiera su zona verdadera. Si la cobertura baja
del 80% probablemente se rompió la normalización de ciudad/barrio.

Medido al construir la fase (muestra determinista de 400): 100% de cobertura y
~89% de acierto de la sugerencia principal.
"""

import random

import pytest
from pydantic import ValidationError

_TAMANO_MUESTRA = 400
_SEMILLA = 7
_COBERTURA_MINIMA = 0.80
_ACIERTO_MINIMO = 0.70


def _hay_credenciales() -> bool:
    try:
        from planeacion.config.settings import Settings

        Settings()
        return True
    except ValidationError:
        return False


@pytest.mark.integration
@pytest.mark.skipif(not _hay_credenciales(), reason="sin SUPABASE_URL/SUPABASE_KEY (ni .env)")
def test_leave_one_out_sobre_la_maestra_real() -> None:
    from planeacion.config.contenedor import crear_contenedor
    from planeacion.domain.servicios.sugeridor_zona import SugeridorDeZona

    clientes = crear_contenedor().clientes.listar()
    candidatos = [c for c in clientes if c.zona is not None and c.ciudad and c.barrio]
    assert len(candidatos) > _TAMANO_MUESTRA, "la maestra sembrada quedó demasiado pequeña"

    muestra = random.Random(_SEMILLA).sample(candidatos, _TAMANO_MUESTRA)
    codigos_muestra = {cliente.codigo for cliente in muestra}
    resto = [c for c in clientes if c.codigo not in codigos_muestra]
    sugeridor = SugeridorDeZona(resto)

    con_sugerencia = 0
    aciertos = 0
    for cliente in muestra:
        sugerencia = sugeridor.sugerir(cliente.ciudad, cliente.barrio)
        if sugerencia is None:
            continue
        con_sugerencia += 1
        if sugerencia.zona_sugerida == cliente.zona:
            aciertos += 1

    cobertura = con_sugerencia / _TAMANO_MUESTRA
    acierto = aciertos / con_sugerencia if con_sugerencia else 0.0
    detalle = f"cobertura={cobertura:.0%}, acierto={acierto:.0%}"
    assert cobertura >= _COBERTURA_MINIMA, f"cobertura por debajo del mínimo: {detalle}"
    assert acierto >= _ACIERTO_MINIMO, f"acierto por debajo del mínimo: {detalle}"
