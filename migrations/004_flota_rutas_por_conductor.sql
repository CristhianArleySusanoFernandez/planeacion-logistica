-- =============================================================================
-- 004_flota_rutas_por_conductor.sql
-- La flota pasa de "17 carros" a 22 RUTAS, varias por conductor.
--
-- Por qué: cambió la persona a cargo de la planeación (octubre 2026) y con ella
-- la operación. La unidad de reparto sigue siendo la ruta (una fila por ruta,
-- numero 1..22), pero ahora un mismo conductor lleva DOS rutas con el mismo
-- vehículo y el mismo auxiliar: FABIAN 1 / FABIAN 2, ANGELICA ARIAS 1 / 2,
-- RAUL 1 / 2, JAIRO GARZON 1 / 2, CARLOS 1 / 2. El sufijo numérico del nombre
-- es lo que distingue las rutas de un mismo conductor.
--
-- Tres columnas nuevas, ninguna obligatoria (la base vieja sigue leyéndose):
--
-- * conductor_clave: el nombre SIN el sufijo ('FABIAN' para FABIAN 1 y 2). Es
--   la clave con la que se agrupan las cargas de un mismo conductor; `conductor`
--   sigue guardando el nombre completo, que es lo que espera facturación.
--
-- * municipio_real: informativo. Las rutas 8..13 son viajeras (MUZO, FLORIAN,
--   GARAGOA, MIRAFLORES, VILLA DELEYVA) y en el modelo de la app caen todas en
--   el municipio OTROS, que es el pool con el que balancea. Perder el nombre
--   real del destino hacía ilegible la pantalla de flota; acá queda guardado.
--   `municipio_id` NO cambia de significado: sigue siendo el pool de balanceo.
--
-- * lado_chiquinquira: 'SUR' o 'NORTE'. La regla dura de Chiquinquirá era
--   posicional (primer carro del pool = sur, segundo = norte) y con cuatro rutas
--   en el municipio eso vaciaba las rutas 3 y 4. Ahora el lado es un dato de la
--   ruta, sale de su zona principal en la hoja BASE, y la regla aplica al PAR de
--   rutas de cada lado: SUR -> {1, 2}, NORTE -> {3, 4}. Dentro del lado deciden
--   el repertorio y el balance.
--
-- Cómo aplicarlo: copiar y ejecutar este archivo completo en el editor SQL de
-- Supabase (Dashboard > SQL Editor). Es idempotente: re-ejecutarlo no pisa nada.
-- =============================================================================

alter table carros add column if not exists conductor_clave     text;
alter table carros add column if not exists municipio_real      text;
alter table carros add column if not exists lado_chiquinquira   text;

alter table carros drop constraint if exists carros_lado_chiquinquira_valido;
alter table carros add constraint carros_lado_chiquinquira_valido check (
    lado_chiquinquira is null or lado_chiquinquira in ('SUR', 'NORTE')
);

-- Arranque razonable para las filas que ya existen: sin sufijo que quitar, la
-- clave del conductor es su propio nombre, y el municipio real es el pool. La
-- resincronización desde el archivo de corte (planeacion-resincronizar) pisa
-- las tres columnas con los datos del día; esto solo evita dejarlas vacías.
update carros set conductor_clave = conductor where conductor_clave is null;

update carros
set municipio_real = municipios.nombre
from municipios
where carros.municipio_id = municipios.id
  and carros.municipio_real is null;
