-- =============================================================================
-- 003_carro_zonas_dia.sql
-- El repertorio pasa a depender del DÍA DE LA SEMANA.
--
-- Por qué: una misma zona no siempre la atiende el mismo carro. Medido sobre
-- los archivos históricos, decenas de zonas cambian de carro según el día
-- ((TUNJA): ASIS va en el 13 casi toda la semana pero en el 12 los jueves;
-- (BARBOSA): MUNICIPIO CITE va en el 5 salvo los sábados, que va en el 3).
-- La tabla decía "el carro 3 puede atender la zona X" pero no decía cuándo.
--
-- Los dos comportamientos conviven y el modelo soporta ambos: una zona-día con
-- UN solo carro habilitado queda fijada, y con VARIOS el balanceador elige.
--
-- Columna `frecuencia`: cuántas veces se observó ese par en el histórico.
-- Sirve para distinguir en la interfaz una regla estable (se repite semana a
-- semana) de un reemplazo puntual (se vio una sola vez), que es una decisión
-- que toma la usuaria, no el script de siembra.
--
-- Cómo aplicarlo: copiar y ejecutar este archivo completo en el editor SQL de
-- Supabase (Dashboard > SQL Editor). Es idempotente: re-ejecutarlo no duplica
-- filas ni pisa lo ya configurado.
-- =============================================================================

-- 1. Las columnas nuevas. `dia_semana` nace nullable porque las filas que ya
--    existen todavía no tienen día; se completa en el paso 3 y recién ahí se
--    exige not null.
alter table carro_zonas add column if not exists dia_semana text;
alter table carro_zonas add column if not exists frecuencia integer not null default 0;

-- 2. Fuera la unicidad vieja: sin esto el paso 3 no puede replicar un mismo par
--    (carro, zona) a los seis días.
alter table carro_zonas drop constraint if exists carro_zonas_carro_id_zona_id_key;

-- 3. Migración de los datos existentes.
--    La configuración que ya hizo la usuaria es implícitamente "todos los días",
--    así que se replica a los seis días laborales para que signifique lo mismo
--    que antes. `frecuencia = 0` (el default) las marca como puestas a mano y
--    nunca observadas en el histórico, distinguibles de las que sembrará
--    `planeacion-sembrar-repertorio`.
--    Sin este paso, al aplicar la migración el balanceador dejaría de encontrar
--    repertorio para cualquier día y mandaría todas las zonas a `zonas_sin_carro`.
update carro_zonas set dia_semana = 'lunes' where dia_semana is null;

insert into carro_zonas (carro_id, zona_id, dia_semana, frecuencia)
select origen.carro_id, origen.zona_id, dia.nombre, origen.frecuencia
from carro_zonas as origen
cross join (values ('martes'), ('miercoles'), ('jueves'), ('viernes'), ('sabado')) as dia (nombre)
where origen.dia_semana = 'lunes'
  and not exists (
      select 1
      from carro_zonas as ya
      where ya.carro_id = origen.carro_id
        and ya.zona_id = origen.zona_id
        and ya.dia_semana = dia.nombre
  );

-- 4. Ahora sí, las restricciones definitivas.
--    El check acepta los SIETE días aunque el negocio trabaje de lunes a sábado:
--    `dia_semana` se deriva de la fecha de los pedidos, y si alguna vez se
--    planea un domingo es preferible que la fila se pueda guardar a que la
--    inserción falle. Sembrar, se siembran seis.
alter table carro_zonas alter column dia_semana set not null;

alter table carro_zonas drop constraint if exists carro_zonas_dia_semana_valido;
alter table carro_zonas add constraint carro_zonas_dia_semana_valido check (
    dia_semana in ('lunes', 'martes', 'miercoles', 'jueves', 'viernes', 'sabado', 'domingo')
);

alter table carro_zonas drop constraint if exists carro_zonas_carro_zona_dia_key;
alter table carro_zonas add constraint carro_zonas_carro_zona_dia_key
    unique (carro_id, zona_id, dia_semana);

-- 5. El índice de lectura: el balanceo siempre pide "el repertorio de este día".
drop index if exists idx_carro_zonas_zona;
create index if not exists idx_carro_zonas_dia_zona on carro_zonas (dia_semana, zona_id);
