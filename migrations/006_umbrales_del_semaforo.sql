-- =============================================================================
-- 006_umbrales_del_semaforo.sql
-- Los dos cortes del semáforo de balance pasan a ser parámetros.
--
-- Por qué: los umbrales eran 10 % y 20 % de coeficiente de variación, de julio
-- de 2026, cuando la flota era otra. Con las 22 rutas actuales **el reparto real
-- de la operación mide entre 25 % y 46 % de CV**, así que los cuatro municipios
-- salían en rojo todos los días —un día normal daba Barbosa 4/6/20,
-- Chiquinquirá 10/23/13, Otros 20/18/33 y Tunja 34/35/29— y un semáforo que
-- siempre está en rojo deja de informar.
--
-- Los nuevos cortes (0,25 y 0,40) se eligieron contra ese piso real: por debajo
-- de 25 % el reparto está mejor que lo que hace la operación a mano, y por
-- encima de 40 % hay carros claramente desiguales incluso con esta flota.
--
-- Esto SOLO cambia el color y el texto de la leyenda. El reparto propuesto es
-- exactamente el mismo: los umbrales no entran en la función de costo.
--
-- Cómo aplicarlo: copiar y ejecutar este archivo completo en el editor SQL de
-- Supabase (Dashboard > SQL Editor). Es idempotente: re-ejecutarlo no duplica
-- filas ni pisa un valor que la usuaria ya haya cambiado.
-- =============================================================================

insert into parametros (clave, valor, descripcion) values
    ('umbral_cv_aceptable', 0.25,
     'Hasta este CV el reparto se ve verde en el semáforo. Los 0,10 de julio de 2026 dejaban los '
     'cuatro municipios en rojo todos los días: el reparto real mide 25 a 46 %.'),
    ('umbral_cv_atencion', 0.40,
     'Hasta este CV el semáforo va en ámbar; por encima, rojo. Solo cambia el color: el reparto '
     'propuesto es el mismo.')
on conflict (clave) do nothing;
