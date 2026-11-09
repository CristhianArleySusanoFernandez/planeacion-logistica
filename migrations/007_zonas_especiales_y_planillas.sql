-- =============================================================================
-- 007_zonas_especiales_y_planillas.sql
-- Marca de zona especial y umbral de planillas desparejas.
--
-- Por qué: trece zonas de la maestra de octubre de 2026 son UN cliente que pide
-- esporádicamente (COMULTRASAN, GAITAN, COMFABOY, PEÑA BLANCA, IMPACTA...) y se
-- despachan aparte con el vehículo que convenga. No tienen repertorio y antes el
-- sistema las leía como "zona sin carro". `zonas.especial` es la ÚNICA fuente de
-- esa marca: ni el balanceador ni la interfaz consultan la lista por nombre.
--
-- Y cinco conductores llevan dos planillas del mismo camión (Fabián, Angélica
-- Arias, Raúl, Carlos, Javier Reyes). `desbalance_planillas` dice desde qué
-- diferencia entre las dos se avisa. Aquí entra con 0,35, el valor inicial que
-- pidió la operación; la 008 lo recalibra.
--
-- Esta migración se aplicó a mano desde el SQL Editor el 6 de noviembre de 2026
-- y se versiona aquí para que el repositorio cuente la historia completa. Es
-- idempotente.
-- =============================================================================

alter table zonas add column if not exists especial boolean not null default false;

-- El nombre en la base lleva el prefijo del municipio: "(BARBOSA): COMULTRASAN LLEVA SEB".
update zonas
   set especial = true
 where trim(split_part(nombre, '):', 2)) in (
    'COMULTRASAN LLEVA SEB', 'GAITAN LLEVA SEB', 'BARBOSA SALIDA PUENTE LLEVA SEB',
    'VIA CITE R5', 'VIA CITE R7', 'PEÑA BLANCA', 'MEDELLIN', 'IMPACTA', 'PIZZA NOSTRA',
    'DISTRIROSAS', 'DISTRIBUCIONES LEON - CONCEPCION', 'ESTADIO REMONTA', 'COMFABOY'
 );

insert into parametros (clave, valor, descripcion) values
    ('desbalance_planillas', 0.35,
     'Diferencia desde la que dos planillas del mismo camión se consideran desparejas, como '
     'fracción de la menor (0,35 = 35 %). Solo avisa: el reparto no cambia.')
on conflict (clave) do nothing;
