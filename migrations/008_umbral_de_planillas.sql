-- =============================================================================
-- 008_umbral_de_planillas.sql
-- El umbral de planillas desparejas sube de 0,35 a 0,75.
--
-- Por qué: medido sobre el reparto real de la operación en los 7 días del 20 al
-- 27 de octubre de 2026 (33 pares camión-día), con 0,35 y comparando clientes,
-- pesos y kilos la alerta salía 26 de 33 días; un aviso que sale casi siempre
-- deja de informar. Con 0,75 y comparando solo pesos y kilos (los clientes
-- salieron de la comparación en el código: la operación reparte las mitades por
-- carga, no por paradas) avisa 6 de 33, y los 6 son desparejos de verdad.
-- Ver docs/dominio.md, «Calibración del umbral de planillas».
--
-- A diferencia de las anteriores, esta SÍ pisa el valor: el 0,35 era el default
-- sin calibrar, no un ajuste de la usuaria. Si después cambia el umbral desde
-- Configuración → Parámetros, no hay que volver a correr esto.
--
-- Cómo aplicarlo: copiar y ejecutar en el SQL Editor de Supabase.
-- =============================================================================

update parametros
   set valor = 0.75,
       descripcion = 'Diferencia desde la que dos planillas del mismo camión se consideran '
                     'desparejas, como fracción de la menor (0,75 = 75 %). Se compara en pesos y '
                     'kilos, no en clientes. Solo avisa: el reparto no cambia.'
 where clave = 'desbalance_planillas';
