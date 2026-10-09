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
  el formato `(MUNICIPIO):  NOMBRE`, por ejemplo `(BARBOSA):  BARBOSA-PUENTE`. El municipio se saca de ese
  paréntesis y **no hace falta que esté al principio**: la maestra trae nombres marcados con una
  letra adelante (`Y (TUNJA): RUTA OCCIDENTE`, `ZZZ(CHIQUINQUIRA): ...`) o con el municipio al final
  (`PARAISO (TUNJA)`), y con el ancla al inicio quedaban todos en `OTROS`. Fuera del inicio solo se
  acepta si es uno de los municipios propios (`MUNICIPIOS_PROPIOS`), porque hay paréntesis
  decorativos que crearían pools fantasma sin ningún carro: `VIAJERA 1 (RAMIRIQUI)` o el `(CHIQUI)`
  que lleva en el medio la zona más larga de Chiquinquirá.
- **Municipio**: el prefijo de la zona. Los principales son `BARBOSA`, `CHIQUINQUIRA`, `TUNJA`. Las zonas sin
  prefijo (rutas "viajeras" o sueltas como `VILLA DE LEYVA`, `RUTA MUZO`) se agrupan en un municipio especial
  llamado `OTROS`. Las rutas **8 a 13** son las viajeras: su `municipio` es `OTROS` —ese es el pool con el
  que se balancean— y `municipio_real` conserva el destino de verdad (`MUZO`, `FLORIAN`, `GARAGOA`,
  `MIRAFLORES`, `VILLA DELEYVA`), que es lo que va a la columna CIUDAD de la hoja `BASE` de salida.
  Municipio por ruta, constante en los 15 archivos de septiembre–octubre de 2026: 1–4 CHIQUINQUIRA,
  5–7 BARBOSA, 8 MUZO, 9 FLORIAN, 10 GARAGOA, 11 MIRAFLORES, 12–13 VILLA DELEYVA, 14–22 TUNJA.
- **Carro / ruta**: la unidad de reparto. Son **22 rutas**, numeradas 1–22 con numeración estable, cada
  una con conductor, auxiliar y municipio (el "pool" con el que se balancea). Un mismo conductor puede
  llevar **dos rutas** con el mismo vehículo y el mismo auxiliar, y el sufijo numérico del nombre es lo
  que las distingue: `FABIAN 1`/`FABIAN 2` (rutas 1 y 2), `ANGELICA ARIAS 1`/`2` (3 y 4), `RAUL 1`/`2`
  (12 y 13), `JAIRO GARZON 1`/`2` (14 y 15), `CARLOS 1`/`2` (16 y 17). `conductor` guarda el nombre
  completo (es lo que espera facturación) y `conductor_clave` el nombre sin el sufijo, que es con lo que
  se vuelven a juntar las rutas de una persona (`agrupar_por_conductor`, el resumen del Paso 3).
- **Pedido / Factura**: una orden de un cliente. Un pedido tiene **varias líneas** (una por producto).
- **Planeación**: el trabajo diario. Consiste en **repartir las zonas del día entre los carros del
  municipio**, buscando que los carros queden **balanceados en cantidad de clientes y en plata (pesos)**.

### Reglas de negocio (importantes)

1. **Chiquinquirá** usa 4 rutas y la regla dura es por **lado**, no por ruta: una zona del sur solo puede
   caer en una ruta del sur (hoy `{1, 2}`) y una del norte en una del norte (`{3, 4}`). El lado de la
   zona se lee de su nombre (`RUTA SUR 4`, `CHIQUIN RUTA 1 NORTE`) y el de la ruta sale de su zona
   principal en la hoja `BASE`, guardado en `carros.lado_chiquinquira`; es un dato de la ruta y no una
   posición en el pool. **Entre las rutas del lado correcto deciden el repertorio y el balance.** Medido
   sobre los 15 archivos de septiembre–octubre de 2026, el lado se respeta en 81 de 93 asignaciones (las
   rutas 3 y 4 atendieron 11 zonas del sur y la 1 una del norte), así que no se puede fijar la ruta: eso
   vaciaría las rutas 3 y 4, que es lo que hacía la versión posicional anterior. Si ninguna ruta del pool
   trae lado configurado, no hay regla que aplicar y manda el balance.
2. **Barbosa** usa ~3 carros; no hay regla explícita de geografía, se hereda de la planeación de la semana
   pasada (cercanía aprendida).
3. **Tunja** usa varias rutas (14–22). Hasta agosto de 2026 incluía un **carro externo (nº 16)** que
   costaba **$160.000/día** y había que evaluar no prenderlo; en la operación de octubre de 2026 **no hay
   carro externo** (la 16 es `CARLOS 1`, propia) y las tres apariciones de una ruta 23 en los archivos son
   refuerzos puntuales, no un externo recurrente. La flota conserva `es_externo` y `costo_diario` porque
   la figura puede volver, pero hoy están en `false` y `0` en las 22 rutas.
4. **Tres variables de equilibrio**: el reparto se juzga por **clientes**, **pesos** (plata) y
   **kilos**, cada uno con su peso en la función de costo (`w_clientes`, `w_pesos`, `w_kilos`, todos
   en 0,5 por defecto). Los kilos los pidió la operación: dos carros pueden quedar parejos en
   clientes y en plata y uno llevar el triple de peso, que es el que termina cargando y descargando.
   El semáforo del Paso 3 lo marca **la peor de las tres**, no el promedio, y los tres CV se
   muestran por separado para ver cuál manda. Los kilos solo son un criterio con la guarda de
   `guarda_kilos` delante; sin ella serían ruido (ver § 5).

5. **Ciclo semanal**: la planeación de un día se parece mucho a la del **mismo día de la semana anterior**.
   Por eso el motor de balanceo arranca ("warm-start") desde la planeación del mismo día de semana previa.
6. **Alertas operativas: metas, no reglas.** La jefatura pidió tres indicadores y ninguno
   restringe el reparto, porque la operación los incumple ella misma todas las semanas:

   - **mínimo de 50 clientes por conductor** en Tunja, Barbosa y Chiquinquirá (las viajeras del pool
     `OTROS` quedan fuera: pocas visitas y mucho kilómetro es su naturaleza). Sobre los 16 archivos
     de septiembre y octubre de 2026, el reparto real lo incumple **20 veces**: Wilmar 7 días, José
     Jiménez 6, José Yovany Salamanca 3, Luis Eduardo 2, Camilo Pacheco 1 y Jairo Garzón 1;
   - **máximo de 110 facturas por conductor**, que el reparto real pasa **19 veces**, siempre los
     mismos dos: Angélica Arias 10 días y Fabián 9, sin que nunca se llamara un carro externo;
   - **promedio por vehículo** = facturas del día ÷ `vehiculos_referencia` (12, el divisor **fijo**
     de la hoja de Julián, no la cantidad de carros con carga: cambiarlo daría otro número y
     rompería la comparación con lo que la operación ya mira). Osciló entre 91 y 112, con un solo
     día por encima de 110.

   Se suman **por conductor y no por ruta**: dos rutas de 30 clientes no son dos problemas, son un
   conductor con 60. Se muestran en el Paso 3 debajo del balance y en la columna *Alerta* de la hoja
   `BASE`; la del promedio, que es del día entero y no cuelga de ninguna ruta, va debajo de la tabla.

7. **Repertorio de zonas por carro y día** (tabla `carro_zonas`, migraciones 002 y 003): cada carro solo
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

   > **Resembrado en octubre de 2026.** La numeración de las rutas cambió de significado
   > (la 13 era de Tunja y hoy es Villa de Leyva; la 16 era el carro externo y hoy es
   > `CARLOS 1`, propia), así que ningún par viejo seguía siendo válido: el repertorio se
   > **vació** —respaldado antes a `salidas/carro_zonas_respaldo_<fecha>.csv` con
   > `planeacion-sembrar-repertorio --vaciar`— y se resembró desde los 16 archivos de
   > septiembre–octubre de 2026. Quedaron **647 pares** con frecuencia ≥ 1 y ninguno en 0:
   > lunes 117, martes 103, miércoles 93, jueves 98, viernes 111, sábado 125. Las filas de
   > la ruta 23 (refuerzos puntuales, no flota) se descartan y se reportan.

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
> guardado desde un libro con macros) o como `.xls`. Todos se cargan igual: `LectorEcomExcel` abre
> los OOXML con openpyxl y traduce los demás a un libro en memoria antes de pasarlos al mismo mapeo
> de columnas. Ni el nombre ni la cantidad de hojas importan: la hoja se elige por su encabezado.
>
> **Un `.xls` son dos formatos distintos y se decide por el contenido, no por el nombre.** Puede ser
> el binario BIFF anterior a 2007 (típico de "Guardar como" en Excel viejo), que traduce
> `lector_ecom_xls` con `xlrd`; o —y esto es lo que descarga hoy la empresa del portal— una **tabla
> HTML con la extensión cambiada**, que arranca con
> `<html xmlns:o="urn:schemas-microsoft-com:office:office">` y traduce `lector_ecom_html` con
> `html.parser` de la stdlib. Excel abre las dos sin chistar, así que la diferencia no se nota hasta
> que falla: `xlrd` muere con *"Expected BOF record; found b'				<htm'"*. El HTML trae una sola
> `<table>` con las 38 columnas de siempre, las fechas en ISO y los totales y kilos como texto —el
> mismo material que el bloque pegado—, declara `charset=us-ascii` mintiendo (los bytes son cp1252)
> y no usa `rowspan`. De haber varias tablas se toma la que más filas tiene: la de datos.

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

> **Guarda de kilos mal cargados.** ECOM trae productos con el peso equivocado en la ficha:
> `CMU. 2 TOSH MIEL GTS FUS` viene a **715,5 kg la unidad** en 18 líneas de $17.279, y por eso los
> totales del 5, 6 y 7 de octubre de 2026 dieron 8.863, 20.978 y 17.562 kg contra los 4.000–5.300 de
> un día normal. Como los kilos entran a la función de costo del balanceo, una sola ficha mal
> cargada decidiría el reparto del día. `domain/servicios/guarda_kilos.py` marca la línea por dos
> reglas: más de `kilos_max_por_unidad` (25 kg) por unidad, o más de 10 veces la mediana de kilos por
> unidad de **ese mismo `Cod.Prod`** dentro del archivo (con al menos 3 apariciones, y sin contar las
> que ya pasaron el techo, que si no corren la mediana). A la línea marcada se le ponen los kilos en
> **cero**: la factura, el cliente y la plata siguen contando porque el pedido existe y se factura;
> lo único que no se puede creer es el peso. El pivote expone `kilos_excluidos` y el detalle, el
> Paso 1 lo avisa, la hoja `PEDIDOS` lo marca en la columna *Kilos revisados* y el validador lo
> cuenta por día. Al cotejar totales contra `PLANEACION` los kilos excluidos se vuelven a sumar: esa
> fila los trae porque la operación no los descartó, y lo que esa prueba verifica es que la app leyó
> la misma entrada. Medido sobre el 6 de octubre: 20.977,92 kg → **4.632,12 kg**, con facturas,
> clientes y pesos idénticos.

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
  esporádico (`activo = false` si no facturó). La columna **I** (sin encabezado) trae la **zona
  principal** de la ruta, de donde se lee el lado de Chiquinquirá. El bloque 1 de la hoja (vehículos
  físicos con código y placa) NO se siembra; el cruce ruta↔vehículo está en
  `docs/mapeo-vehiculos-rutas.md`. **Ojo con los archivos de octubre de 2026**: ahí el bloque 1 está
  desactualizado y sus conductores no coinciden con el bloque 2, así que no sirve ni para la placa.

Hojas del Excel que **NO** se migran (son solo andamiaje de fórmulas que la app hará internamente):
`INFORMACIÓN DE LA MAESTRA`, `DN BARRIOS`, `cta cliente`, `Copia_PLANEACION`. Las hojas
`RESUMEN DE AGOTADOS Y ASESORES` y `ASESORES AGOTADOS FINAL` son de **otro proceso** (agotados/asesores) y
quedan **fuera del alcance**.

---

## 6.bis Parámetros editables

Los números que el negocio puede querer mover viven en la tabla `parametros` (migración 005) y se
editan en **Configuración → Parámetros**, sin despliegue. El **catálogo** —qué parámetros existen,
cuánto valen por defecto y qué hace cada uno— vive en `domain/modelo/parametros.py`, que es la
fuente de verdad; la tabla guarda **solo los valores cambiados** y repite las descripciones para que
se entienda abriéndola en Supabase.

La asimetría importa: si la tabla está vacía, le falta una clave o alguien borró una fila, **manda
el default del dominio**. Así la app funciona en una base sin migrar y una fila borrada por error no
se convierte en un cero silencioso que apague una variable del equilibrio. Un cero *explícito* sí se
respeta: apagar una variable es una decisión válida. El botón "Restaurar valores por defecto" borra
las filas en vez de reescribirlas, para no tener dos fuentes de verdad.

| Clave | Default | Qué hace y por qué ese valor |
|---|---|---|
| `w_clientes` | 0,5 | Cuánto pesa igualar clientes entre carros. Las tres variables del equilibrio van con el mismo peso porque las tres importan igual. |
| `w_pesos` | 0,5 | Cuánto pesa igualar la plata. |
| `w_kilos` | 0,5 | Cuánto pesa igualar los kilos. Medido: con 0,5 el CV de kilos baja de 36,8 % a 36,1 % y la coincidencia sube a 91,6 % (ver § 10.9). |
| `w_frecuencia` | 0,30 | El desempate por costumbre. Bajo a propósito: rompe empates, no sobrecarga. Salió de medir julio 2026 (§ 10.7); subirlo a 0,45 empeora todo levemente. |
| `min_clientes_conductor` | 50 | Meta de la jefatura para Tunja, Barbosa y Chiquinquirá. **Solo avisa**: el reparto real la incumple 20 veces en 16 días. |
| `max_facturas_conductor` | 110 | Facturas desde las que conviene revisar el carro externo. **Solo avisa**: Angélica Arias y Fabián lo pasan casi todos los días sin externo. |
| `vehiculos_referencia` | 12 | Divisor del "Promedio Vh". **Fijo a propósito**: es el de la hoja que la operación mira, y usar "los carros con carga" daría otro número. |
| `kilos_max_por_unidad` | 25 | Techo de la guarda de kilos. Una unidad de venta es una caja o un display; ningún producto sano de 2026 se acerca, y hay fichas con 715,5 kg (ver § 5). |

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

8. **Operación de octubre de 2026 (otra persona a cargo, flota y repertorio nuevos)**: medido
   sobre los 12 días que traen su `.xls` de ECOM —la entrada real del Paso 1, emparejada por fecha
   de pedidos con `planeacion-validar --ecom`— la coincidencia promedio es **91,1 %** (mediana
   92,1 %, entre 77,6 % y 98,8 %). Los 12 `.xls` cuadran **exactos** con la fila "Ventas Totales" de
   su `PLANEACION`, hasta el centavo y el gramo, así que la entrada reconstruida es la que se planeó.
   Es una medición **in-sample**: esos mismos archivos sembraron el repertorio, así que el número es
   optimista y sirve de referencia, no de resultado.

   > **El desbalance no es de la app, es del día.** El validador calcula también el CV del reparto
   > que hizo la operación, con las mismas zonas, el mismo pool, los mismos carros (incluidos los
   > vacíos) y la misma fórmula, y los dos quedan casi iguales: 24,8 % contra 25,7 % en clientes y
   > 32,0 % contra 32,1 % en pesos. Por municipio la app queda mejor en Barbosa (13,9/14,0 contra
   > 15,5/16,3), algo peor en pesos de Chiquinquirá (25,5 contra 23,1) y empatada en OTROS y TUNJA.
   > Los CV altos de TUNJA (28,6/45,9) y OTROS (35,9/42,7) vienen de cómo caen los pedidos y de lo
   > estrecho que es el repertorio recién sembrado, no del balanceador.

9. **Kilos como tercera variable del equilibrio** (octubre 2026): medido sobre los 12 días con
   `.xls` de ECOM, con la guarda de kilos activa y comparando contra el mismo reparto de la
   operación. `--w-kilos 0` reproduce exactamente la referencia de 91,1 %.

   | | w_kilos 0 | **w_kilos 0,5** | w_kilos 0,5 + w_frecuencia 0,45 |
   |---|---|---|---|
   | Coincidencia | 91,1 % | **91,6 %** | 91,5 % |
   | Mediana | 92,1 % | **92,7 %** | 92,7 % |
   | Mínimo | 77,6 % | **78,9 %** | 77,6 % |
   | CV clientes | 24,8 % | 25,5 % | 25,5 % |
   | CV pesos | 32,0 % | **31,6 %** | 31,7 % |
   | CV kilos | 36,8 % | **36,1 %** | 36,2 % |

   Se queda el default (0,5 con `w_frecuencia` en 0,30): mejora kilos y pesos, sube la coincidencia
   medio punto y el único costo es +0,7 puntos de CV de clientes, dentro del margen. Subir
   `w_frecuencia` a 0,45 no aporta: empeora todo levemente. Contra el reparto real de la operación
   la propuesta queda mejor o igual en las tres variables (25,5 contra 25,7 en clientes, 31,6 contra
   32,1 en pesos, 36,1 contra 36,8 en kilos).

### Fuera del alcance entregado

- **OR-Tools**: el balanceador es heurístico (búsqueda local por movimientos e intercambios). Se
  evaluó un solver como segunda iteración y no fue necesario: los CV alcanzados son buenos donde
  el reparto es estructuralmente mejorable (ver § 9).
- **Recomendación automática del carro 16**: la flota guarda `es_externo` y `costo_diario`
  ($160.000/día), y esos datos se muestran en la configuración, pero la app **no** calcula todavía
  si conviene no prenderlo y repartir su carga al carro 13. Hoy esa decisión de costo la sigue
  tomando Rudy mirando el reparto.
