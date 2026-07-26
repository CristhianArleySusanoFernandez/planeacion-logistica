# Planeación Logística — Distribuciones Santiago de Tunja

Aplicación Python (arquitectura hexagonal + Supabase) que automatiza la planeación logística diaria.
El contexto completo del negocio y la arquitectura están en [CLAUDE.md](CLAUDE.md).

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
[`migrations/002_carro_zonas.sql`](migrations/002_carro_zonas.sql).
Los scripts son idempotentes (`create table if not exists`), se pueden correr más de una vez.

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

## Pivote por zona (proceso diario)

Con la base ya sembrada, el pivote del día se genera desde el `.xlsx` crudo de ECOM:

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

Imprime el reparto por municipio con semáforos de desbalance (CV < 10% verde, 10–20% amarillo,
> 20% rojo) mostrando el CV **inicial → final**. Con `--interactivo` Rudy mueve zonas entre carros
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
conductor, tipo de vehículo, costumbre). El balanceador solo asigna una zona a un carro que
la tenga permitida — en el reparto inicial, en el warm-start y en cada movimiento de la
mejora —; las zonas compartidas por varios carros son donde tiene libertad de elegir. Una
zona **viajera** cuyo único carro elegible es de otro municipio se balancea en el pool de
ese carro (ej. RAQUIRA, de OTROS, viaja en el carro 2 de Chiquinquirá); una zona que ningún
carro activo permite queda **sin asignar** y se reporta (`zonas_sin_carro`) para que Rudy la
configure. Con la tabla vacía (base sin configurar) todo funciona como antes.

El repertorio se siembra desde las hojas `PLANEACION` históricas (col A = carro, col B = zona):

```bash
uv run planeacion-sembrar-repertorio datos/*.xlsm
```

Es idempotente (upsert por par carro-zona), reporta los carros/zonas del histórico que no
casan con la base, el repertorio resultante por carro y cuántas zonas activas quedaron sin
ningún carro. Después se ajusta a mano en la UI (Configuración → Zonas por carro).

## Interfaz web (Streamlit)

La UI lleva a Rudy paso a paso por la planeación del día — es un adaptador de entrada más:
toda la lógica vive en los casos de uso.

```bash
uv run streamlit run src/planeacion/infraestructura/adaptadores/entrada/web/app.py
```

1. **Cargar ECOM**: sube el `.xlsx` crudo, corre el pivote y muestra el resumen del día
   (con warning si el archivo trae pedidos colados de otras fechas).
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

## Desarrollo

```bash
uv run ruff check          # lint
uv run mypy src            # tipos (estricto)
uv run pytest              # pruebas (la de integración se salta sin credenciales)
```

Estructura hexagonal en `src/planeacion/`: `domain/` (núcleo puro), `application/` (casos de uso y
puertos), `infraestructura/` (adaptadores Excel/Supabase/CLI), `config/` (settings y wiring).
`domain` y `application` no importan nada de `infraestructura`.
