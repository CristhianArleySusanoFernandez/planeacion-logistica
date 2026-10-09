-- =============================================================================
-- 005_parametros.sql
-- Los números que la operación puede querer mover, en una tabla y no en el código.
--
-- Por qué: hasta ahora los pesos de la función de costo y los umbrales de las
-- alertas vivían como defaults del dominio, y cambiarlos pedía un despliegue.
-- Son decisiones del negocio, no del programa: el mínimo de clientes por
-- conductor y el máximo de facturas los puso la jefatura, el divisor de 12 sale
-- de la hoja de Excel que usan todos los días, y los pesos del equilibrio se
-- ajustan midiendo. Nada de eso debería necesitar un programador.
--
-- El dominio sigue teniendo sus defaults y manda si la tabla está vacía o le
-- falta una clave: la app no se rompe en una base sin migrar, y una fila borrada
-- por error vuelve al valor conocido en vez de dejar un cero silencioso.
--
-- Cómo aplicarlo: copiar y ejecutar este archivo completo en el editor SQL de
-- Supabase (Dashboard > SQL Editor). Es idempotente: re-ejecutarlo no duplica
-- filas ni pisa los valores que la usuaria ya haya cambiado.
-- =============================================================================

create table if not exists parametros (
    clave        text primary key,
    valor        numeric(12, 4) not null,
    descripcion  text not null
);

-- La semilla NO pisa lo que ya esté cargado (`do nothing`): si alguien ajustó un
-- peso y se vuelve a correr la migración, su ajuste sobrevive. Para volver a los
-- defaults está el botón de la pestaña Parámetros, que es una decisión explícita.
insert into parametros (clave, valor, descripcion) values
    ('w_clientes', 0.5,
     'Cuánto pesa igualar la cantidad de clientes entre carros (0 lo apaga).'),
    ('w_pesos', 0.5,
     'Cuánto pesa igualar la plata entre carros (0 lo apaga).'),
    ('w_kilos', 0.5,
     'Cuánto pesa igualar los kilos entre carros, que es lo que hay que cargar y descargar.'),
    ('w_frecuencia', 0.3,
     'Cuánto pesa la costumbre: entre carros que pueden atender la zona, prefiere al que la '
     'viene atendiendo ese día. Bajo a propósito: rompe empates, no sobrecarga.'),
    ('min_clientes_conductor', 50,
     'Meta de clientes por conductor en Tunja, Barbosa y Chiquinquirá. Solo avisa: la operación '
     'la incumple 20 veces en 16 días y el reparto no se modifica.'),
    ('max_facturas_conductor', 110,
     'Facturas por conductor desde las que conviene revisar si hace falta carro externo. Solo '
     'avisa: Angélica Arias y Fabián lo pasan casi todos los días sin externo.'),
    ('vehiculos_referencia', 12,
     'Divisor fijo del "Promedio Vh" de la hoja de la empresa. No es la cantidad de carros con '
     'carga: se deja fijo para que el número sea comparable con el que ellos ya miran.'),
    ('kilos_max_por_unidad', 25,
     'Kilos por unidad desde los que una línea de ECOM se considera mal cargada y sus kilos no '
     'entran al reparto. Hay fichas con 715,5 kg la unidad.')
on conflict (clave) do nothing;
