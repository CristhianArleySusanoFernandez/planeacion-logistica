# Dominio y arquitectura — Planeación Logística · Distribuciones Santiago de Tunja

> Documento de referencia del proyecto: qué resuelve, con qué vocabulario y bajo qué arquitectura.
> Todo el dominio se nombra en español, y también el código, los comentarios y los commits.
> Para instalar, correr y desplegar la aplicación, ver el [README](../README.md).

---

## 1. Qué es este proyecto

Aplicación en **Python** que automatiza el proceso diario de **planeación logística** de una empresa
distribuidora. Hoy el proceso lo hace **a mano** una empleada (Rudy) en un Excel gigante lleno de macros
VBA. El objetivo es reemplazar ese Excel por una aplicación con **arquitectura hexagonal**, base de datos
**Supabase** e interfaz en **Streamlit**, sin perder ninguna información relevante y generando la misma
salida que hoy consume el proceso de facturación.

**Regla de producto:** la máquina propone, Rudy decide. Nada se asigna de forma irreversible sin que ella
pueda revisarlo y ajustarlo.

---

## 2. El proceso de negocio (glosario)

- **Cliente**: un negocio que compra. Cada cliente pertenece a una **zona fija** y se visita un **día fijo
  de la semana** (un cliente de los miércoles siempre cae en miércoles).
- **Zona** (a veces llamada *ruta* en los datos viejos): agrupación geográfica de clientes. Su nombre tiene
  el formato `(MUNICIPIO):  NOMBRE`, por ejemplo `(BARBOSA):  BARBOSA-PUENTE`.
- **Municipio**: el prefijo de la zona. Los principales son `BARBOSA`, `CHIQUINQUIRA`, `TUNJA`. Las zonas sin
  prefijo (rutas "viajeras" o sueltas como `VILLA DE LEYVA`, `RUTA MUZO`) se agrupan en un municipio especial
  llamado `OTROS`.
- **Carro**: vehículo de reparto. Son **17 carros fijos**, cada uno con conductor, placa y auxiliar. Cada
  carro pertenece a un municipio (a un "pool" de carros que atiende ese municipio).
- **Pedido / Factura**: una orden de un cliente. Un pedido tiene **varias líneas** (una por producto).
- **Planeación**: el trabajo diario. Consiste en **repartir las zonas del día entre los carros del
  municipio**, buscando que los carros queden **balanceados en cantidad de clientes y en plata (pesos)**.

### Reglas de negocio (importantes)

1. **Chiquinquirá** usa 2 carros: las zonas "sur" van al **carro 1** y las "norte" al **carro 2** (regla dura).
2. **Barbosa** usa ~3 carros; no hay regla explícita de geografía, se hereda de la planeación de la semana
   pasada (cercanía aprendida).
3. **Tunja** usa varios carros e incluye un **carro externo (nº 16)** que cuesta **$160.000/día**. Si al
   repartir un carro queda con pocos clientes, hay que evaluar **no prender el 16** y repartir esa carga al
   carro 13 (propio). Esta decisión de costo la toma finalmente Rudy, pero la app la recomienda.
4. **Ciclo semanal**: la planeación de un día se parece mucho a la del **mismo día de la semana anterior**.
   Por eso el motor de balanceo arranca ("warm-start") desde la planeación del mismo día de semana previa.
5. **Repertorio de zonas por carro y día** (tabla `carro_zonas`, migraciones 002 y 003): cada carro solo
   puede atender las zonas de su repertorio y el balanceador elige únicamente entre carros elegibles.
   El repertorio **depende del día de la semana**: `(TUNJA): ASIS` va en el carro 13 casi toda la semana
   pero en el 12 los jueves; `(BARBOSA): MUNICIPIO CITE` va en el 5 salvo los sábados, que va en el 3.
   Una zona-día con **un solo** carro habilitado queda fijada; con **varios**, el balanceador elige.
   Una zona viajera cuyo único carro elegible es de otro municipio se balancea en el pool de ese carro
   (ej. RAQUIRA → carro 2 de Chiquinquirá); sin ningún carro elegible **ese día** queda en
   `zonas_sin_carro` (aviso en la UI). Repertorio vacío = comportamiento clásico. Se siembra del
   histórico con `planeacion-sembrar-repertorio datos/*.xlsm` (hoja `PLANEACION`, col A = carro,
   col B = zona) y se edita en la UI (Configuración → Zonas por carro, con selector de día).
   La regla dura de Chiquinquirá prevalece sobre él.

   > **Dónde vive la decisión del día**: la resuelve el **caso de uso** (`dia_de(pivote.fecha)`) y le
   > pasa al `Balanceador` solo el repertorio de ese día. El servicio de dominio sigue recibiendo un
   > `Mapping[str, Set[str]]` plano carro → zonas y no sabe que los días existen; por eso los cuatro
   > puntos donde ya respetaba el repertorio (reparto inicial, warm-start, movimientos, intercambios)
   > y `AjustadorDeAsignacion` —que valida contra el `repertorio` que viaja dentro de
   > `ResultadoBalanceo`— pasaron a respetar el del día sin cambiar una línea.

   > La columna `frecuencia` cuenta cuántas veces se observó el par en el histórico: `0` es "puesto a
   > mano, nunca visto", y un `1` suele ser un reemplazo puntual más que una regla. Es información
   > para que la usuaria decida en la interfaz, no un filtro que aplique la siembra.

   > **Desempate por costumbre**: cuando una zona-día tiene varios carros elegibles, la elegibilidad
   > sola no alcanza —para el balanceador un carro que atendió la zona 8 veces y otro que la atendió 1
   > son igual de válidos— y elegía por carga. Por eso la función de costo lleva un tercer término,
   > `w_frecuencia * penalización media`, donde cada zona paga `1 - f/F` (`f` = veces que ese carro la
   > atendió ese día, `F` = el máximo entre sus carros elegibles): 0 para el dominante y hasta casi 1
   > para el más minoritario. La frecuencia `0` es **neutra** (no hay evidencia, no hay castigo), no
   > la peor opción. El peso es bajo a propósito: el balance sigue mandando y la costumbre solo
   > inclina lo marginal. Sigue siendo la máquina proponiendo: no fija zonas ni quita opciones.

   > **Qué día es "el día"**: siempre el de los **pedidos**, nunca el de entrega. El nombre del
   > archivo (`DEL 01 PARA EL 04 AGOSTO`) nombra los dos, pero el pivote, el warm-start y
   > `planeaciones.dia_semana` se manejan con la fecha de los pedidos, así que la siembra la deriva
   > del bloque de ECOM de la hoja `PEDIDOS` para que el repertorio quede en la misma clave que el
   > balanceador consulta. Un archivo que cubre **dos jornadas** no se puede atribuir (el reparto
   > manual las trata como un bloque único) y se descarta, igual que los que no cuadran con sus
   > propios totales o traen un volumen anómalamente bajo.

---

## 3. Arquitectura — hexagonal (ports & adapters)

Tres anillos. **Las dependencias apuntan siempre hacia adentro.** `domain` y `application` **no importan
nada** de `infrastructure`.

- **`domain`** (núcleo puro): entidades, objetos de valor y servicios de dominio. Cero dependencias externas
  (nada de Supabase, openpyxl, Streamlit). Solo Python estándar (`dataclasses`, `decimal`, `datetime`).
  Las dependencias apuntan hacia adentro: `domain` y `application` no importan nada de `infraestructura`.
- **`application`**: casos de uso (puertos de entrada) y las **interfaces de los puertos de salida**
  (repositorios, lectores, exportadores). Orquesta el dominio. Depende solo de `domain`.
- **`infraestructura`**: los **adaptadores** que implementan los puertos: lectura/escritura de Excel,
  repositorios Supabase, la CLI y la UI Streamlit.
- **`config`**: settings y *wiring* (composición de dependencias / inyección).

### Estructura de carpetas

```
PlaneacionLogistica/
├── README.md
├── docs/                           # este documento y el mapeo vehículos↔rutas
├── pyproject.toml
├── .env.example
├── migrations/                     # SQL para el esquema de Supabase
├── src/
│   └── planeacion/
│       ├── domain/
│       │   ├── modelo/             # Cliente, Zona, Municipio, Carro, Pedido, ...
│       │   ├── servicios/          # AgregadorPorZona, ResolutorDeZona, Balanceador, ...
│       │   └── errores.py
│       ├── application/
│       │   ├── puertos/
│       │   │   ├── entrada/        # interfaces de casos de uso
│       │   │   └── salida/         # interfaces de repos / lectores / exportadores
│       │   ├── casos_uso/          # implementaciones de los casos de uso
│       │   └── dto/
│       ├── infraestructura/
│       │   └── adaptadores/
│       │       ├── entrada/
│       │       │   ├── cli/
│       │       │   └── web/        # Streamlit (fase posterior)
│       │       └── salida/
│       │           ├── excel/      # lector ECOM, exportador
│       │           └── supabase/   # repositorios
│       └── config/                 # settings + contenedor de dependencias
└── tests/
    ├── unit/
    └── integration/
```

---

## 4. Stack técnico

- **Python 3.11+**, gestionado con **uv** (`uv init`, `uv add`, `uv run`).
- **Supabase** (Postgres) vía el cliente **`supabase`** (supabase-py). Esquema versionado con SQL en
  `migrations/`.
- **openpyxl** para leer/escribir Excel (usar `read_only=True` al leer los .xlsm, que pesan ~30 MB).
- **Streamlit** para la interfaz (fase posterior).
- **OR-Tools** para el balanceador (fase posterior; la primera versión del balanceador es heurística).
- **pytest** para pruebas, **ruff** para lint/format, **mypy** para tipos.
- **pydantic-settings** para configuración por entorno (`.env`).

---

## 5. Formato del archivo de ECOM (entrada cruda diaria)

Es un `.xlsx` con una hoja llamada `Hoja1`. Tiene **una fila por línea de producto** (un pedido con 5
productos ocupa 5 filas). Columnas relevantes:

> **Extensiones aceptadas.** El mismo export llega a veces como `.xlsm` (el mismo OOXML, solo que
> guardado desde un libro con macros) o como `.xls` (el binario BIFF anterior a 2007, típico de
> "Guardar como" en Excel viejo). Los tres se cargan igual: `LectorEcomExcel` abre los dos primeros
> con openpyxl y traduce el tercero con `xlrd` a un libro en memoria
> (`lector_ecom_xls.abrir_xls_como_libro`) antes de pasarlo al mismo mapeo de columnas. Ni el nombre
> ni la cantidad de hojas importan: la hoja se elige por su encabezado.

| Col | Campo        | Uso                                                           |
|-----|--------------|---------------------------------------------------------------|
| A   | Tipo         | siempre "PEDIDO"                                               |
| B   | Pedido       | número de pedido = identifica la **factura**                  |
| D   | Fecha        | fecha del pedido                                              |
| G   | nit/ced      | documento del cliente                                          |
| H   | R. Social    | `"CODIGO-RAZÓN SOCIAL"` → el **código de cliente** es el prefijo antes del primer `-` |
| I   | Cliente      | `"CODIGO-NOMBRE"` (mismo código que H)                        |
| J   | Ciudad       | ej. `"15001 - TUNJA"`                                          |
| K   | Barrio       |                                                               |
| L   | Zona         | (viene casi siempre vacía; NO usar como zona real)            |
| M   | Direccion    |                                                               |
| N   | Telefono     |                                                               |
| O   | Total        | total de la **factura** (viene como texto, repetido en cada línea del pedido) |
| P   | Asesor       | ej. `"10947-MATILDA"`                                          |
| V   | Producto     | nombre del producto                                           |
| W   | Cantidad     |                                                               |
| AE  | Total2       | total de la **línea** (texto con decimales)                   |
| AI  | Kilos        | kilos de la **línea**                                         |

**El código de cliente se obtiene** partiendo `H` (o `I`) por el primer `-` y tomando la parte izquierda.
Convertir `O` y `AE` a `Decimal` (vienen como string).

**La zona NO está en este archivo**: se asigna cruzando el código de cliente contra la maestra (tabla
`clientes` en Supabase). Los clientes que no estén en la maestra quedan como **no resueltos (#N/D)** y hay
que sugerirles zona (fase de clientes nuevos).

### El mismo bloque, pegado dentro de los `.xlsm`

Cada `.xlsm` de planeación trae una copia literal del ECOM de su día en la hoja `PEDIDOS`, **a partir
de la columna S** (`S`=Tipo, `T`=Pedido, `V`=Fecha, `Z`=R. Social, `AA`=Cliente, `AG`=Total de factura,
`AV`=Iva, `AW`=Total de línea, `BA`=Kilos en gramos). El mapeo es idéntico al del `.xlsx` suelto y es
consistente en los 27 archivos disponibles, así que el parseo se comparte
(`lector_ecom.leer_bloque_ecom`, con desplazamiento de columna).

**Trampa del formato**: a la izquierda del bloque, en `A`–`P`, hay otra tabla —la de trabajo manual—
con encabezados homónimos: `Fecha`, `Kilos` y dos `Total` más. Mapeando la fila 1 completa habría
**cuatro** columnas `Total` y el `Kilos` de la columna K ganaría el match por estar primero: el archivo
se leería mal en silencio. Por eso el bloque se ancla en su propio `Tipo`/`Pedido` de la S en adelante.

Esa tabla de `A`–`P` es además la lista de facturas **efectivamente trabajadas**, y no siempre coincide
con el bloque de la derecha: en `DEL 14 PARA EL 16 JULIO` el ECOM se pegó antes de que cerrara la
jornada y quedó con 2.435 facturas contra las 2.097 que se planearon. De ahí que la validación exija
que los totales cuadren con la fila "Ventas Totales" de `PLANEACION` antes de dar por buena la medición.

Dos archivos (`DEL 14 PARA EL 16 JULIO` y `DEL 20-21 PARA EL 23 JULIO`) traen **dos jornadas** que se
planearon juntas; sus totales de `PLANEACION` son la suma de ambas, así que ahí no se filtra por fecha.

---

## 6. Datos para sembrar Supabase (desde los .xlsm de referencia)

Los archivos `.xlsm` de planeación traen las hojas de las que se siembra la base. Como los datos son
viejos y el orden de columnas varía entre archivos, el comando de siembra **imprime las primeras filas
de cada hoja y valida los encabezados antes de escribir nada** (`planeacion-sembrar --solo-inspeccion`).
Mapeo esperado:

- **`clientes`** ← hoja **`MAESTRA`**: `A`=Codigo, `B`=Direccion, `C`=CodigoPostal, `D`=Ciudad,
  `E`=Ciudad2/Barrio, `F`=RUTA (nombre de zona). El `zona_id` del cliente se resuelve casando el texto de
  `RUTA` contra `zonas.nombre`.
- **`zonas`** ← se derivan de los valores distintos de `RUTA`. El **municipio** se parsea del prefijo
  `(XXX):`; si no hay prefijo, el municipio es `OTROS`. Marcar la regla especial de Chiquinquirá (sur/norte)
  según el texto del nombre.
- **`correcciones_ubicacion`** ← hoja **`CAMBIOS`**: `A`=Codigo, `F`=Ciudad Real, `G`=Barrio Real (más
  columnas de contexto). Corrige la ubicación mal traída por ECOM.
- **`overrides_zona`** ← hoja **`martha ojo`**: `A`=Codigo del cliente, columna de zona forzada (texto tipo
  `(BARBOSA): ...`). Fuerza la zona de clientes puntuales.
- **`carros`** (flota) ← hoja **`BASE`**, **bloque 2** (desde la fila-encabezado `Ruta | Facturas |
  ... | CIUDAD`): son las **rutas de reparto 1–18** que usan Rudy y facturación, con conductor,
  auxiliar y municipio deducido de CIUDAD (lo que no es Barbosa/Chiquinquirá/Tunja → OTROS). La ruta
  **16** es el carro externo (`es_externo = true`, `costo_diario = 160000`) y la **18** un refuerzo
  esporádico (`activo = false` si no facturó). El bloque 1 de la hoja (vehículos físicos con código y
  placa) NO se siembra; el cruce ruta↔vehículo está en `docs/mapeo-vehiculos-rutas.md`.

Hojas del Excel que **NO** se migran (son solo andamiaje de fórmulas que la app hará internamente):
`INFORMACIÓN DE LA MAESTRA`, `DN BARRIOS`, `cta cliente`, `Copia_PLANEACION`. Las hojas
`RESUMEN DE AGOTADOS Y ASESORES` y `ASESORES AGOTADOS FINAL` son de **otro proceso** (agotados/asesores) y
quedan **fuera del alcance**.

---

## 7. Salida (para facturación)

La salida principal que consume facturación es la hoja **`ECOM`**: cada cliente (código) con la **ruta/carro**
que le tocó. La app debe poder exportar un `.xlsx` que replique esa hoja, y adicionalmente las hojas
`PLANEACION` y `BASE` con su estructura, para no perder información. (El exportador es de una fase posterior.)

---

## 8. Convenciones de código

- Nombres de dominio en **español** (`Cliente`, `Zona`, `Carro`, `Pedido`, `Planeacion`, `AgregadorPorZona`).
- Objetos de valor como **`@dataclass(frozen=True)`**. **`Decimal`** para dinero, nunca `float`.
- **Ninguna** lógica de negocio en los adaptadores; solo traducción de datos.
- Cada servicio de dominio y cada caso de uso lleva **pruebas** (pytest).
- Los puertos son **interfaces** (`typing.Protocol` o `abc.ABC`) en `application/puertos`.
- Errores de dominio propios en `domain/errores.py` (no lanzar excepciones de librerías desde el dominio).

---

## 9. Validación

El pivote por zona que calcule la app desde el ECOM crudo debe **reproducir** el que aparece en la hoja
`PLANEACION` del `.xlsm` del mismo día. Para validar, lee los totales directamente de esa hoja y compáralos.
Como referencia aproximada del dataset del 26 de junio: ~**1343 facturas**, ~**$149.379.870**, ~**6472
kilos**, ~**1139 clientes únicos** (leer los valores exactos del propio archivo, no confiar en estos números).

---

## 10. Alcance construido

El proyecto se desarrolló en seis etapas, todas terminadas:

1. **Fundación**: esqueleto hexagonal, esquema de Supabase y siembra desde el Excel de referencia.
2. **Ingesta y pivote**: lectura del ECOM crudo, normalización, resolución de zona por cliente y
   pivote por zona, validado contra la hoja `PLANEACION` del mismo día.
3. **Clientes nuevos**: asistente que sugiere zona a los #N/D por voto de vecinos (ciudad + barrio).
4. **Balanceador**: reparto de zonas a carros por heurística, con warm-start desde la planeación del
   mismo día de la semana anterior y repertorio de zonas por carro.
5. **UI y exportación**: Streamlit para revisar y ajustar con recálculo en vivo, exportación del
   Excel para facturación e histórico de planeaciones en Supabase.
6. **Validación por lotes**: `planeacion-validar` reprocesa `.xlsm` históricos desde su propio ECOM
   embebido y coteja la propuesta contra el reparto manual, sin warm-start. Sobre 5 archivos al azar
   (agosto 2026, semilla 20260810): **81,2 %** de coincidencia promedio, entre 79,2 % y 84,5 %.
7. **Repertorio por día y desempate por costumbre**: medido sobre los 22 días de julio 2026 que cuadran
   con sus propios totales, la coincidencia promedio pasó de **81,7 %** (repertorio sin día) a
   **93,4 %** (con día) y a **95,2 %** con el desempate por frecuencia en 0,30 — 96,4 % dejando fuera
   el archivo que planeó dos jornadas juntas. Sobre los dos archivos que nunca entraron a la siembra
   (13 y 14 de agosto), **94,5 %**. Los CV por municipio no se movieron en ninguno de los dos pasos.
   El peso se ajusta con `planeacion-validar --w-frecuencia N` y `planeacion-balancear --w-frecuencia N`
   (0 lo apaga y reproduce el comportamiento anterior).

### Fuera del alcance entregado

- **OR-Tools**: el balanceador es heurístico (búsqueda local por movimientos e intercambios). Se
  evaluó un solver como segunda iteración y no fue necesario: los CV alcanzados son buenos donde
  el reparto es estructuralmente mejorable (ver § 9).
- **Recomendación automática del carro 16**: la flota guarda `es_externo` y `costo_diario`
  ($160.000/día), y esos datos se muestran en la configuración, pero la app **no** calcula todavía
  si conviene no prenderlo y repartir su carga al carro 13. Hoy esa decisión de costo la sigue
  tomando Rudy mirando el reparto.
