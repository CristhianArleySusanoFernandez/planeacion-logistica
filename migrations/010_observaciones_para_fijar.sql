-- =============================================================================
-- 010_observaciones_para_fijar.sql
-- Parámetro nuevo: cuántas observaciones hacen falta para que una zona con una
-- sola ruta posible ese día salga FIJA (candado) en el Paso 3.
--
-- Medido el 13 de noviembre de 2026 sobre el repertorio resembrado: 131 de 446
-- zonas-día (29 %) estaban fijas por UNA sola observación, la mitad de ellas del
-- planeador anterior. Con 2, esas zonas salen «sugeridas»: el balanceador las
-- deja en su única ruta (no hay otra información), pero la planeadora puede
-- moverlas a cualquier ruta activa de su municipio, y al guardar la planeación
-- la ruta elegida entra al conteo (planeacion-sembrar-repertorio --desde-guardadas).
--
-- Frecuencia 0 («este carro no», heredado o marcado a mano) fija siempre, sin
-- importar el parámetro. Con 1 vuelve el comportamiento anterior al Prompt 26.
-- No cambia el reparto automático: solo qué se puede mover a mano y cómo se ve.
--
-- Idempotente: si la fila ya existe, no la toca (el valor es de la operación).
-- =============================================================================

insert into parametros (clave, valor, descripcion) values
    ('observaciones_para_fijar', 2,
     'Cuántas veces hay que haber visto a la única ruta de una zona ese día para que salga fija '
     '(candado) en el Paso 3. Por debajo sale «sugerida» y se puede mover a cualquier ruta del '
     'municipio. Con 1 vuelve al comportamiento anterior. Frecuencia 0 («este carro no») fija '
     'siempre. No cambia el reparto automático.')
on conflict (clave) do nothing;
