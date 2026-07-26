-- =============================================================================
-- 001_esquema_inicial.sql
-- Esquema inicial de Planeación Logística — Distribuciones Santiago de Tunja.
--
-- Cómo aplicarlo: copiar y ejecutar este archivo completo en el editor SQL de
-- Supabase (Dashboard > SQL Editor). Es idempotente (create ... if not exists).
-- =============================================================================

-- -----------------------------------------------------------------------------
-- municipios: agrupación de zonas por el prefijo "(XXX):" del nombre de la zona.
-- Las zonas sin prefijo (rutas viajeras/sueltas) van al municipio especial OTROS.
-- -----------------------------------------------------------------------------
create table if not exists municipios (
    id     bigint generated always as identity primary key,
    nombre text not null unique
);

-- -----------------------------------------------------------------------------
-- zonas: agrupación geográfica de clientes (en los datos viejos se llama RUTA).
-- regla_chiquinquira aplica solo a zonas de Chiquinquirá: SUR → carro 1,
-- NORTE → carro 2 (regla dura del negocio).
-- -----------------------------------------------------------------------------
create table if not exists zonas (
    id                  bigint generated always as identity primary key,
    nombre              text not null unique,
    municipio_id        bigint not null references municipios (id),
    regla_chiquinquira  text check (regla_chiquinquira in ('SUR', 'NORTE')),
    activa              boolean not null default true
);

create index if not exists idx_zonas_municipio on zonas (municipio_id);

-- -----------------------------------------------------------------------------
-- carros: la flota fija de reparto (hoja BASE del Excel de referencia).
-- numero es el código del vehículo tal como aparece en la hoja BASE (texto,
-- p. ej. '108', '820'). El carro externo (el "16" de la planeación) se marca
-- con es_externo = true y costo_diario = 160000 cuando se identifique su placa.
-- -----------------------------------------------------------------------------
create table if not exists carros (
    id            bigint generated always as identity primary key,
    numero        text not null unique,
    conductor     text,
    placa         text,
    auxiliar      text,
    municipio_id  bigint references municipios (id),
    es_externo    boolean not null default false,
    costo_diario  numeric(12, 2) not null default 0,
    activo        boolean not null default true
);

create index if not exists idx_carros_municipio on carros (municipio_id);

-- -----------------------------------------------------------------------------
-- clientes: la maestra de clientes (hoja MAESTRA). El código es la identidad
-- natural (prefijo antes del primer '-' en las columnas H/I del ECOM diario).
-- documento y razon_social no vienen en la MAESTRA: se completan en la fase de
-- ingesta del ECOM diario, por eso son nullables.
-- -----------------------------------------------------------------------------
create table if not exists clientes (
    codigo        text primary key,
    documento     text,
    razon_social  text,
    direccion     text,
    barrio        text,
    ciudad        text,
    zona_id       bigint references zonas (id),
    dia_visita    text,
    activo        boolean not null default true
);

create index if not exists idx_clientes_zona on clientes (zona_id);

-- -----------------------------------------------------------------------------
-- correcciones_ubicacion: hoja CAMBIOS. Corrige la ciudad/barrio que ECOM trae
-- mal para clientes puntuales. cliente_codigo no es FK a clientes a propósito:
-- puede llegar una corrección de un cliente que aún no está en la maestra.
-- unique(cliente_codigo) hace la re-siembra idempotente.
-- -----------------------------------------------------------------------------
create table if not exists correcciones_ubicacion (
    id              bigint generated always as identity primary key,
    cliente_codigo  text not null unique,
    ciudad_real     text,
    barrio_real     text
);

-- -----------------------------------------------------------------------------
-- overrides_zona: hoja "martha ojo". Fuerza la zona de clientes puntuales por
-- encima de lo que diga la maestra. Mismo criterio de cliente_codigo que arriba.
-- -----------------------------------------------------------------------------
create table if not exists overrides_zona (
    id              bigint generated always as identity primary key,
    cliente_codigo  text not null unique,
    zona_id         bigint not null references zonas (id)
);

create index if not exists idx_overrides_zona on overrides_zona (zona_id);

-- -----------------------------------------------------------------------------
-- planeaciones: una corrida de planeación diaria (cabecera).
-- -----------------------------------------------------------------------------
create table if not exists planeaciones (
    id          bigint generated always as identity primary key,
    fecha       date not null,
    dia_semana  text not null,
    creada_en   timestamptz not null default now()
);

create index if not exists idx_planeaciones_fecha on planeaciones (fecha);

-- -----------------------------------------------------------------------------
-- planeacion_asignaciones: el detalle de una planeación — qué zona quedó en qué
-- carro y con qué totales (facturas, clientes únicos, pesos, kilos).
-- carro_id es nullable: una zona puede estar aún sin asignar mientras Rudy revisa.
-- -----------------------------------------------------------------------------
create table if not exists planeacion_asignaciones (
    id               bigint generated always as identity primary key,
    planeacion_id    bigint not null references planeaciones (id) on delete cascade,
    zona_id          bigint not null references zonas (id),
    carro_id         bigint references carros (id),
    num_facturas     integer not null default 0,
    clientes_unicos  integer not null default 0,
    total_pesos      numeric(14, 2) not null default 0,
    total_kilos      numeric(14, 3) not null default 0
);

create index if not exists idx_asignaciones_planeacion on planeacion_asignaciones (planeacion_id);
create index if not exists idx_asignaciones_zona on planeacion_asignaciones (zona_id);
create index if not exists idx_asignaciones_carro on planeacion_asignaciones (carro_id);
