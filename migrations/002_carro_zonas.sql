-- =============================================================================
-- 002_carro_zonas.sql
-- Repertorio de zonas por carro: qué zonas puede atender cada carro (por
-- conocimiento del conductor, tipo de vehículo o costumbre del negocio).
--
-- El balanceador solo asigna una zona a un carro que la tenga en su repertorio;
-- las zonas compartidas por varios carros son donde tiene libertad de elegir.
-- Si la tabla está vacía (base sin configurar) se mantiene el comportamiento
-- clásico: cualquier carro del municipio puede atender cualquier zona.
--
-- Cómo aplicarlo: copiar y ejecutar este archivo completo en el editor SQL de
-- Supabase (Dashboard > SQL Editor). Es idempotente (create ... if not exists).
-- =============================================================================

create table if not exists carro_zonas (
    id        bigint generated always as identity primary key,
    carro_id  bigint not null references carros (id) on delete cascade,
    zona_id   bigint not null references zonas (id) on delete cascade,
    unique (carro_id, zona_id)
);

create index if not exists idx_carro_zonas_zona on carro_zonas (zona_id);
