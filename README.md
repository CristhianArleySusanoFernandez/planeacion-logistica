# Planeación Logística — Distribuciones Santiago de Tunja

Aplicación Python (arquitectura hexagonal + Supabase) que automatiza la planeación logística diaria.
El contexto completo del negocio y la arquitectura están en [`docs/dominio.md`](docs/dominio.md).

## Requisitos

- [uv](https://docs.astral.sh/uv/) (gestiona Python y dependencias)
- Un proyecto de [Supabase](https://supabase.com)

## Instalación

```bash
uv sync
```

## Configuración

1. Copia `.env.example` a `.env`.
2. En el dashboard de Supabase (Settings → API) copia la **URL** del proyecto y la clave
   **service_role** (la siembra escribe en todas las tablas; la clave `anon` puede chocar con RLS):

```
SUPABASE_URL=https://xxxx.supabase.co
SUPABASE_KEY=eyJ...
```

## Aplicar las migraciones

Abre el **SQL Editor** del dashboard de Supabase y pega/ejecuta, en orden, el contenido de
[`migrations/001_esquema_inicial.sql`](migrations/001_esquema_inicial.sql) y
[`migrations/002_carro_zonas.sql`](migrations/002_carro_zonas.sql) y
[`migrations/003_carro_zonas_dia.sql`](migrations/003_carro_zonas_dia.sql).
Los scripts son idempotentes (`create table if not exists`), se pueden correr más de una vez.
La 003 le agrega al repertorio la dimensión del **día de la semana** y **replica la
configuración que ya exista a los seis días laborales**, así lo ya cargado a mano sigue
significando lo mismo que antes.

## Sembrar la base desde el Excel de referencia

Los `.xlsm` de planeación van en `datos/` (no se versionan). Luego:

```bash
# Solo inspección: imprime el mapeo de columnas y los conteos, sin escribir nada
uv run planeacion-sembrar datos/DEL_24_PAR_EL_26_JUNIO.xlsm --solo-inspeccion

# Siembra real (idempotente: re-correr no duplica)
uv run planeacion-sembrar datos/DEL_24_PAR_EL_26_JUNIO.xlsm
```

El comando primero imprime las primeras filas de cada hoja (`MAESTRA`, `CAMBIOS`, `martha ojo`,
`BASE`) con el mapeo de columnas detectado, valida los encabezados y solo entonces siembra:
municipios → zonas → carros → clientes → correcciones → overrides. Al final reporta conteos por
tabla y filas no mapeables.

> **La flota son las rutas de reparto, no los vehículos físicos**: la hoja `BASE` tiene dos
> tablas y `carros` se siembra del **bloque 2** (desde la fila-encabezado `Ruta | Facturas |
> ... | CIUDAD`): rutas 1–18 con conductor, auxiliar y municipio deducido de CIUDAD (lo que no
> es Barbosa/Chiquinquirá/Tunja cae en OTROS). La ruta **16** es el carro externo
> (`es_externo = true`, $160.000/día) y la **18** es un refuerzo esporádico que queda
> `activo = false` si no facturó. El bloque 1 (vehículos con código y placa) no se siembra;
> el cruce ruta ↔ vehículo está en [`docs/mapeo-vehiculos-rutas.md`](docs/mapeo-vehiculos-rutas.md).

## Resincronizar la configuración desde el archivo más reciente

La siembra de arriba es para arrancar de cero. Cuando la operación cambia —otra persona a cargo,
otra flota, la maestra corregida— la configuración se **resincroniza** desde el `.xlsm` más
reciente, que es el archivo de corte:

```bash
# Modo reporte (lo que hace por defecto): no escribe nada
uv run planeacion-resincronizar "datos/DEL 06-10 PARA EL 08-10.xlsm"

# Aplicar, y después verificar recalculando el reporte contra la base ya escrita
uv run planeacion-resincronizar "datos/DEL 06-10 PARA EL 08-10.xlsm" --aplicar
```

Sincroniza cinco cosas: la **flota** (bloque 2 de `BASE`: conductor con sufijo, `conductor_clave`,
auxiliar, municipio del pool y `municipio_real`, lado de Chiquinquirá), las **zonas** (columna RUTA
de `MAESTRA`), los **clientes** (`MAESTRA` para zona/ciudad/barrio/dirección y `MAESTRA COMPLETA`
para documento y razón social), las **correcciones** (`CAMBIOS`) y los **overrides**
(`martha ojo`). Todo queda en consola y en `salidas/resincronizacion_<fecha>.md` como
`antes → después`.

Dos reglas que no se negocian:

- **Nada se borra.** Lo que está en la base y no en el archivo se lista en el reporte (las zonas con
  su número de clientes, los clientes con su código) para decidirlo a mano. La única excepción son
  las rutas fuera de 1–22, que quedan `activo = false` —los refuerzos puntuales no son flota— y
  tampoco se borran.
- **Documento y razón social solo se rellenan si están vacíos.** Si alguien los corrigió en la app,
  la hoja no los pisa. Zona, ciudad, barrio y dirección sí se actualizan: ahí la maestra es la
  fuente y se corrige a diario.

## Pivote por zona (proceso diario)

Con la base ya sembrada, el pivote del día se genera desde el archivo crudo de ECOM. Sirven las tres
extensiones en que suele llegar — `.xlsx`, `.xlsm` y `.xls` — y vale tanto para los comandos de abajo
como para la interfaz web:

```bash
uv run planeacion-pivote datos/pedidos24-26Junio.xlsx
uv run planeacion-pivote datos/pedidos24-26Junio.xlsx --fecha 2026-06-24 --exportar-csv pivote.csv
```

Imprime la tabla por municipio (facturas, clientes únicos, pesos y kilos por zona), los totales
generales, los clientes sin zona (#N/D o en la maestra sin RUTA) y los pedidos excluidos por fecha.
Sin `--fecha` pivotea la fecha válida más frecuente del archivo; el ECOM real a veces trae colados
pedidos viejos con la fecha dañada (texto tipo `46190`) y esos se reportan, no se pierden.

> **Validación**: `tests/integration/test_pivote_contra_planeacion.py` comprueba que el pivote
> reproduce la hoja `PLANEACION` del `.xlsm` del mismo día, zona por zona, leyendo los valores
> esperados del propio archivo.

## Asistente de clientes nuevos (#N/D)

Cuando el pivote encuentra clientes sin zona (no están en la maestra o están sin RUTA), el asistente
sugiere la zona más probable por **voto mayoritario de los vecinos** con la misma ciudad y barrio
(igual que hace Rudy a mano filtrando la MAESTRA), y pide confirmación cliente por cliente:

```bash
uv run planeacion-resolver-nuevos datos/pedidos24-26Junio.xlsx [--fecha 2026-06-24]
```

Opciones por cliente: `[S]` aceptar la sugerencia, `[A]` elegir una alternativa, `[M]` buscar una zona
manualmente, `[O]` omitir. Solo lo confirmado se persiste: el cliente nuevo se agrega completo a la
maestra (y no vuelve a salir como #N/D); el que estaba sin RUTA solo recibe su zona. La comparación de
ciudad/barrio normaliza acentos, espacios y el prefijo DANE del ECOM (`15001 - TUNJA` ≡ `TUNJA`).

> Calidad medida con leave-one-out sobre la maestra real (400 clientes): 100% recibe sugerencia y la
> principal acierta ~89%. Lo vigila `tests/integration/test_sugeridor_contra_maestra.py`.

## Balanceador (reparto de zonas a carros)

Reparte las zonas del día entre los carros de cada municipio buscando que queden parejos en
clientes y en plata. Arranca de la planeación previa del mismo día de la semana (**warm-start**,
si hay una guardada) o de un round-robin por peso, y mejora con movimientos e intercambios:

```bash
uv run planeacion-balancear datos/pedidos24-26Junio.xlsx [--fecha] [--w-clientes 0.5] [--w-pesos 0.5] [--interactivo]
```

Imprime el reparto por municipio con semáforos de desbalance (CV bajo 10% verde, 10–20% amarillo,
sobre 20% rojo) mostrando el CV **inicial → final**. Con `--interactivo` Rudy mueve zonas entre carros
y ve el recálculo en vivo; al final el comando pregunta si guardar la planeación (nada se persiste
sin confirmar). Reglas duras: las zonas de Chiquinquirá SUR van al primer carro del pool y las
NORTE al segundo, y no se pueden mover.

> **Notas de los datos reales**: (1) la tabla `carros` son las rutas de reparto 1–18 del
> bloque 2 de la hoja BASE (pools: Chiquinquirá {1,2}, Barbosa {3,4,5}, Otros {6–10},
> Tunja {11–17}; la 18 está inactiva), la misma numeración que usan Rudy y facturación;
> (2) en OTROS el CV alto es estructural (rutas viajeras geográficas: VENTAQUEMADA trae 78
> clientes ella sola); (3) Chiquinquirá queda fijada 100% por la regla SUR/NORTE (la ruta 1
> es la SUR y la 2 la NORTE, igual que en la referencia).

## Repertorio de zonas por carro

Cada carro tiene un **repertorio limitado de zonas** que puede atender (conocimiento del
conductor, tipo de vehículo, costumbre), **y ese repertorio depende del día de la semana**:
la misma zona no siempre la reparte el mismo carro. En el histórico, `(TUNJA): ASIS` va en
el carro 13 casi toda la semana pero en el **12 los jueves**, y `(BARBOSA): MUNICIPIO CITE`
va en el 5 salvo los **sábados**, que va en el 3. Una zona-día con un solo carro habilitado
queda **fijada**; con varios, el balanceador elige entre ellos.

El día lo resuelve el **caso de uso** a partir de la fecha del pivote y le pasa al
`Balanceador` solo el repertorio de ese día, así el servicio de dominio sigue viendo un mapa
plano carro → zonas y no se entera de que los días existen. El balanceador solo asigna una
zona a un carro que la tenga permitida — en el reparto inicial, en el warm-start y en cada
movimiento de la mejora —; las zonas compartidas por varios carros son donde tiene libertad de elegir. Una
zona **viajera** cuyo único carro elegible es de otro municipio se balancea en el pool de
ese carro (ej. RAQUIRA, de OTROS, viaja en el carro 2 de Chiquinquirá); una zona que ningún
carro activo permite queda **sin asignar** y se reporta (`zonas_sin_carro`) para que Rudy la
configure. Con la tabla vacía (base sin configurar) todo funciona como antes.

El repertorio se siembra desde las hojas `PLANEACION` históricas (col A = carro, col B = zona),
cruzándolas con el **bloque de ECOM pegado en la hoja `PEDIDOS`** para saber de qué día es cada
archivo:

```bash
uv run planeacion-sembrar-repertorio datos/*.xlsm
```

El día **no** sale del nombre del archivo: los nombres tienen erratas (`DEL_24_PAR_EL_26`) y
además nombran el día de *entrega*, mientras que todo el sistema —el pivote, el warm-start,
`planeaciones.dia_semana`— se maneja con el día de los *pedidos*. Sembrar por el día de entrega
dejaría el repertorio en una clave que el balanceador nunca consulta.

Se siembra **todo lo observado**, sin mínimo, con la **frecuencia** de cada trío
(carro, zona, día) — qué conservar lo decide la usuaria en la matriz, no el script. El reporte
final muestra: la distribución por veces observado (1 / 2 / 3+), los archivos **descartados** con
su motivo, los carros del histórico que **no están en la base** y en qué días aparecieron (los
refuerzos salen sobre todo los sábados), el repertorio resultante por carro, las zonas activas
sin ningún carro, y cuántos pares quedaron con **frecuencia 0** — los que no salieron de este
histórico, o sea configuración manual o restos del backfill de la migración 003.

Un archivo se **descarta** (se reporta y no siembra) cuando cubre **dos jornadas** —el reparto
manual las trata como un bloque único y no hay forma de decir a cuál pertenece cada zona—,
cuando el bloque de ECOM pegado **no cuadra** con los totales de su propia hoja `PLANEACION`
(mismo criterio que `planeacion-validar`), cuando no trae ninguna fecha legible, o cuando tiene
un **volumen anómalo**: menos de un cuarto de la mediana de zonas del lote, que es como se
detecta un archivo abandonado a medias.

Es idempotente (upsert por trío carro-zona-día; re-correr actualiza las frecuencias).

Con `--borrar-frecuencia-cero` la siembra además **borra** los pares que quedaron en 0 —los que
no salieron de ningún histórico— dejando solo lo observado. Es destructivo, así que va detrás de
un flag y avisa antes qué zonas quedan **sin ningún carro** al borrar. Sirve sobre todo después
de aplicar la migración 003: su backfill replicó a los seis días la configuración que estaba sin
día, y mientras esas filas siguen ahí habilitan combinaciones que el histórico nunca vio y
diluyen el efecto del día.

Después se ajusta a mano en la UI (Configuración → Zonas por carro), que muestra
**un día a la vez**:

- **Selector de día** arriba de los filtros de municipio, «solo zonas sin carro» y búsqueda.
- Columna **«Veces visto»** por fila: `13×8 · 12×1` es "el carro 13 hizo esta zona 8 veces y el 12
  una sola". Un `⚠` marca las filas con algún par visto una única vez —probable reemplazo puntual,
  no una regla— y abajo hay un panel que los junta todos para repasarlos de un tirón. `×0` es un par
  configurado a mano, que nunca se observó en el histórico.
- **Copiar de otro día**: como la mayoría de los días se parecen, se copia uno entero y después se
  ajustan las diferencias. **Reemplaza, no acumula** (marca y desmarca), avisa cuántas casillas va a
  mover y pide confirmar.

El guardado sigue siendo automático por casilla, sin botón.

## Validación contra las planeaciones manuales

Mide qué tan cerca queda la propuesta automática de lo que Rudy hizo a mano, sobre varios días.
No hacen falta los `.xlsx` de ECOM originales: cada `.xlsm` de planeación es autosuficiente —
en la hoja `PEDIDOS`, a partir de la **columna S**, trae pegado el ECOM crudo del día (la entrada),
y en la hoja `PLANEACION` el reparto manual (el resultado a superar).

```bash
uv run planeacion-validar "datos/DEL 07 PARA EL 09 JULIO.xlsm"
uv run planeacion-validar --muestra 5 "datos/*.xlsm" --exportar-csv diferencias.csv

# Con los .xls sueltos de ECOM como entrada del Paso 1 (el archivo real de producción)
uv run planeacion-validar "datos/*.xlsm" --ecom "datos/infpedidos*.xls"
```

> Los `.xls` que descarga la empresa **no son `.xls`**: son una tabla HTML con la extensión
> cambiada. Se leen igual (ver `lector_ecom_html`), pero si alguna vez falla la lectura, ese es el
> primer lugar donde mirar.

`--ecom` cambia el **origen de la entrada**: en vez del bloque pegado en el `.xlsm` usa los `.xls`
sueltos que la empresa descarga de ECOM, que es lo que la app recibe en producción por el Paso 1 (el
bloque pegado es una copia, y en al menos un archivo histórico se pegó a mitad de jornada). El
emparejamiento es **por fecha de pedidos**: la del `.xls` sale de su nombre
(`infpedidos20261007….xls`) y la del `.xlsm` de la columna `Fecha` de su bloque, nunca del nombre del
`.xlsm` —esos traen erratas y nombran el día de *entrega*—. Un día sin su `.xls` no se mide y se
reporta.

Por cada archivo imprime los totales de ambos lados (control de que la lectura fue correcta),
cuántas zonas coincidieron y la lista de diferencias. Al final: la tabla resumen con promedio,
mediana, mínimo y máximo; una fila **por día** con fecha, día de la semana, coincidencia y CV por
municipio (el promedio esconde la forma de los datos); el CV promedio por municipio; y las
diferencias zona por zona del **peor día**, con el carro manual contra el propuesto. `--muestra N` elige N archivos al azar con una **semilla fija** que se reporta,
para poder repetir la corrida. El CSV (`archivo, fecha, zona, municipio, carro_manual,
carro_propuesto, clientes, pesos`) sirve para ver si una zona difiere **sistemáticamente** —eso
delata una regla de negocio faltante— o solo un día, que es apenas otra forma válida de equilibrar.

Dos decisiones que hacen honesta la medición:

- El balanceo corre **sin warm-start** (`usar_historico=False`): si partiera de la planeación
  guardada de ese mismo día de semana, estaría midiéndose contra sí misma. La salida lo dice.
- **No se filtra por fecha** (`todas_las_fechas=True`): dos archivos cubren dos jornadas que se
  planearon juntas, y sus totales de `PLANEACION` son la suma de ambas.

El porcentaje principal se calcula sobre la **intersección** (las zonas que ambos lados asignaron),
porque una zona que la app no produjo es un hueco de cobertura de la maestra y no un desacuerdo de
reparto; el pesimista, que cuenta esas como fallo, se imprime al lado. Si los totales no cuadran, el
día se reporta y **queda fuera del resumen**: en `DEL 14 PARA EL 16 JULIO` el ECOM se pegó antes de
que cerrara la jornada (2.435 facturas en el bloque contra 2.097 planeadas), así que compararlo
mediría la propuesta contra una entrada que Rudy nunca tuvo.

> Medición de **octubre 2026** sobre los 12 días con `.xls` de ECOM: **91,1 %** de coincidencia
> promedio (mediana 92,1 %, entre 77,6 % y 98,8 %), con los 12 archivos cuadrando exactos contra su
> `PLANEACION`. Es in-sample —esos días sembraron el repertorio—, así que es referencia y no
> resultado. El CV del reparto real queda casi igual al propuesto (25,7 % contra 24,8 % en clientes,
> 32,1 % contra 32,0 % en pesos): el desbalance es del día, no de la app. Cada archivo pesa ~30 MB:
> contar ~1 min por día analizado.

## Interfaz web (Streamlit)

La UI lleva a Rudy paso a paso por la planeación del día — es un adaptador de entrada más:
toda la lógica vive en los casos de uso.

```bash
uv run streamlit run src/planeacion/infraestructura/adaptadores/entrada/web/app.py
```

1. **Cargar ECOM**: sube el archivo crudo (`.xlsx`, `.xlsm` o `.xls`), corre el pivote y muestra el
   resumen del día (con warning si el archivo trae pedidos colados de otras fechas).
2. **Clientes nuevos**: tabla de #N/D con la zona sugerida por voto de vecinos; cada cliente
   tiene un selector con la sugerencia, las alternativas, búsqueda manual u omitir.
3. **Reparto de carros**: la pantalla principal. Resumen de balance por municipio con
   semáforos (CV inicial → final), un tab por municipio con las tablas por carro, y controles
   para mover zonas entre carros con recálculo en vivo (el selector de destino solo ofrece
   carros que permiten esa zona). Si hay zonas sin ningún carro elegible salen en un aviso
   arriba. "Regenerar reparto" (con confirmación) vuelve a balancear desde cero.
4. **Exportar y guardar**: genera el Excel para facturación y lo descarga; "Guardar planeación"
   persiste en Supabase (nada se guarda sin ese clic) y habilita el warm-start del próximo
   mismo día de semana.

**⚙ Configuración** (en la barra lateral): tablas editables de carros, zonas, correcciones
de ubicación y overrides de zona, todas con **filtro de texto** y **alta/baja de filas**
(`num_rows="dynamic"`): "Guardar cambios" hace el diff — nuevas → insert, editadas → update,
eliminadas → delete. Borrar una zona/carro con referencias (clientes, planeaciones) se
bloquea con un error que sugiere desactivarla. El tab **Zonas por carro** edita el
repertorio (multiselect por carro + resumen de carros sin configurar) y el tab Zonas muestra
la vista inversa de solo lectura «carros que la atienden» (`⚠ sin carro` para las huérfanas,
filtrable).

El tab **Clientes** es la maestra (~9.000 registros): buscador por código, razón social o zona
—parcial y sin acentos—, filtros por zona (incluido `⚠ sin zona`, los que caen como no
resueltos en el paso 2) y por municipio, y edición de la zona y de los datos de ubicación.
Como son muchos, **no lista nada hasta que haya un filtro activo** y después pagina de a 50.
Un cliente no se borra: se **desactiva** con la casilla `Activo`, para no perder historial.
La lista se lee una sola vez por sesión y el filtrado ocurre en Python, porque la búsqueda
sin acentos no se puede hacer en la consulta sin `unaccent`.

## Exportación a Excel (salida para facturación)

El exportador replica el layout del `.xlsm` de referencia (inspeccionado, no supuesto):

- **ECOM** — la hoja que consume facturación: `Etiquetas de fila | Mín. de RUTA`, una fila
  por **cliente** con su carro asignado (`#N/A` si quedó sin zona) y cierre `Total general`.
- **PLANEACION** — el pivote: filas `Promedio Vh` y `Ventas Totales` (E en **kilos**),
  encabezados en la fila 4 y una fila por zona (E en **gramos**, como el archivo viejo),
  más la fila `#N/D` si hay clientes sin zona.
- **BASE** — resumen por carro: `Ruta | Facturas | Clientes | Pesos | Kilos | CONDUCTOR |
  AUX | CIUDAD` + zonas asignadas concatenadas.
- **PEDIDOS** — detalle por factura (extra para consulta): fecha, pedido, cliente, ubicación,
  total, kilos, asesor, zona (CUADRANTE) y carro.

> **Nota**: la app escribe el `numero` del carro de la BD, que desde la re-siembra del
> bloque 2 de BASE **son los números de ruta 1–18 que facturación conoce** — la salida
> coincide 1:1 con la referencia.

Lo vigilan `tests/unit/test_exportador_excel.py` (layout y totales con datos de ejemplo) y
`tests/integration/test_exportacion_ecom_real.py` (flujo completo con el ECOM real:
encabezados idénticos a la referencia y totales que reproducen el pivote).

## Despliegue en Streamlit Community Cloud

1. **Subir el repo a GitHub.** Verificar antes que `.env` y `.streamlit/secrets.toml` **no** van
   en el commit (están en `.gitignore`); sí van `.streamlit/config.toml` (el tema),
   `requirements.txt` y `uv.lock`.
2. Crear cuenta en [share.streamlit.io](https://share.streamlit.io) y conectar la cuenta de GitHub.
3. **Create app → Deploy a public app from GitHub** y llenar:
   - *Repository*: el repo del proyecto.
   - *Branch*: `main`.
   - *Main file path*: `src/planeacion/infraestructura/adaptadores/entrada/web/app.py`
4. En **Advanced settings**:
   - *Python version*: **3.12** o superior (Community Cloud no usa `runtime.txt`; la versión se
     elige aquí, y por defecto pone 3.12. El proyecto pide `>=3.11`).
   - *Secrets*: pegar el contenido de [`.streamlit/secrets.toml.example`](.streamlit/secrets.toml.example)
     con los valores reales (los mismos `SUPABASE_URL` y `SUPABASE_KEY` del `.env` local, con la
     clave **service_role**). Se pueden cambiar después en *Manage app → Settings → Secrets*.
5. **Deploy**. La primera vez tarda unos minutos instalando dependencias.

Notas del entorno:

- Las credenciales se leen sin cambiar código: `Settings` mira primero las variables de entorno y
  el `.env` (desarrollo local) y, si no las encuentra, `st.secrets` (Cloud).
- Community Cloud busca los archivos de dependencias en orden y **`uv.lock` tiene prioridad sobre
  `requirements.txt`**. Los dos están en el repo y son equivalentes (`requirements.txt` se genera
  del lock, ver su encabezado): con `uv.lock` instala con `uv sync`, y `requirements.txt` queda de
  respaldo. Al cambiar dependencias hay que regenerarlo para que no se desincronicen.
- El paquete se instala a sí mismo (la línea `.` al final de `requirements.txt`): el código vive en
  `src/` y sin eso `import planeacion` falla en Cloud.
- La app no depende de la carpeta `datos/` (no existe en producción): el único origen de datos es
  el `file_uploader`, y los archivos temporales van a `tempfile.gettempdir()`.
- El logo es opcional: se muestra si existe
  `src/planeacion/infraestructura/adaptadores/entrada/web/assets/logo.png`.

### Limitación conocida del plan gratuito: la app se duerme

El plan gratuito donde corre la app la **suspende tras ~15 minutos sin uso** y tarda cerca de un
minuto en volver a levantar (arranque en frío: contenedor nuevo, dependencias, primera conexión a
Supabase). **No se arregla con código**: es el plan. La barra lateral lo avisa —"la primera carga del
día puede tardar un minuto"— para que nadie piense que se colgó.

Si molesta, las salidas son las mismas que para Supabase: un ping programado que la mantenga
despierta, o un plan pago. Ninguna está implementada.

### Limitación conocida del plan gratuito: Supabase se pausa

Un proyecto de Supabase en el plan gratuito **se pausa solo tras varios días sin actividad**. Con el
proyecto pausado la app no puede leer nada, y muestra un mensaje explicando cómo reactivarlo
(*supabase.com → el proyecto → Restore/Resume*, y recargar 1-2 minutos después). Es una intervención
manual, así que si la herramienta no se usa todos los días conviene resolverlo de una de dos formas:

- **Mantenerlo despierto**: agregar una consulta liviana programada (por ejemplo un workflow de
  GitHub Actions cada pocas horas) a la misma automatización que ya evita que Streamlit se duerma.
- **Plan pago**: si la empresa depende de que la herramienta esté disponible sin que nadie tenga que
  entrar a reactivarla, un plan pago de Supabase elimina la pausa por inactividad.

Ninguna de las dos está implementada todavía.

## Desarrollo

```bash
uv run ruff check          # lint
uv run ruff format         # formato (--check para solo verificar)
uv run mypy src            # tipos (strict = true en pyproject.toml)
uv run pytest              # pruebas (las de integración se saltan sin credenciales)
```

Estructura hexagonal en `src/planeacion/`: `domain/` (núcleo puro), `application/` (casos de uso y
puertos), `infraestructura/` (adaptadores Excel/Supabase/CLI/Streamlit), `config/` (settings y wiring).
`domain` y `application` no importan nada de `infraestructura`. El detalle de las capas, el glosario
del negocio y las reglas están en [`docs/dominio.md`](docs/dominio.md).
