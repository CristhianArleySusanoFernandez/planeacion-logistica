-- =============================================================================
-- 009_divisor_del_promedio_por_vehiculo.sql
-- `vehiculos_referencia` cambia de significado; el valor NO cambia.
--
-- Antes la alerta del Paso 3 dividía las facturas del día por este parámetro
-- (12) y el Excel dividía por las rutas con zonas ese día: dos números distintos
-- para la misma cosa. Desde el Prompt 24 hay UNA función y UN divisor para los
-- dos, y la fila 2 del Excel vuelve a ser la fórmula de la hoja de Julián
-- (`=+C3/<divisor>`), que facturación compara.
--
-- Qué significa ahora el parámetro:
--   > 0  anulación manual: se usa tal cual (hoy 12).
--   = 0  automático: camiones activos, es decir las claves de conductor
--        distintas entre las rutas activas (hoy 17).
--
-- Por qué se queda en 12: el umbral de 110 (`max_facturas_conductor`) y el 12
-- son UNA sola regla de la operación, la de 80–110 pedidos por vehículo. Con 17
-- el mismo día daría 76 en vez de 108 y la alerta de carro externo dejaría de
-- activarse sin que nadie lo decidiera. Si algún día se cambia el divisor, hay
-- que recalibrar `max_facturas_conductor` y la regla de externo con Julián.
--
-- Esta migración solo actualiza la descripción. Es idempotente.
-- =============================================================================

update parametros
   set descripcion = 'Divisor del "Promedio Vh" (facturas del día ÷ vehículos), el mismo en la alerta '
                     'del Paso 3 y en la fila 2 del Excel. 0 = automático: camiones activos (claves de '
                     'conductor distintas de las rutas activas). 12 es el valor con el que está '
                     'calibrada la regla de 80–110 pedidos por vehículo de la operación: si cambia, hay '
                     'que recalibrar max_facturas_conductor con Julián.'
 where clave = 'vehiculos_referencia';
