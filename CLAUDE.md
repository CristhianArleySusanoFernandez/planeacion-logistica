# CLAUDE.md — Planeación Logística · Distribuciones Santiago de Tunja

> Este archivo es el contexto permanente del proyecto. Léelo completo al inicio de cada sesión.
> Todo el dominio se nombra en español; el código, comentarios y commits también en español.

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
5. **Repertorio de zonas por carro** (tabla `carro_zonas`, migración 002): cada carro solo puede atender
   las zonas de su repertorio y el balanceador elige únicamente entre carros elegibles. Una zona viajera
   cuyo único carro elegible es de otro municipio se balancea en el pool de ese carro (ej. RAQUIRA →
   carro 2 de Chiquinquirá); sin ningún carro elegible queda en `zonas_sin_carro` (aviso en la UI).
   Repertorio vacío = comportamiento clásico. Se siembra del histórico con
   `planeacion-sembrar-repertorio datos/*.xlsm` (hoja `PLANEACION`, col A = carro, col B = zona) y se
   edita en la UI (Configuración → Zonas por carro). La regla dura de Chiquinquirá prevalece sobre él.

---

## 3. Arquitectura — hexagonal (ports & adapters)

Tres anillos. **Las dependencias apuntan siempre hacia adentro.** `domain` y `application` **no importan
nada** de `infrastructure`.

- **`domain`** (núcleo puro): entidades, objetos de valor y servicios de dominio. Cero dependencias externas
  (nada de Supabase, openpyxl, Streamlit). Solo Python estándar (`dataclasses`, `decimal`, `datetime`).
- **`application`**: casos de uso (puertos de entrada) y las **interfaces de los puertos de salida**
  (repositorios, lectores, exportadores). Orquesta el dominio. Depende solo de `domain`.
- **`infrastructure`**: los **adaptadores** que implementan los puertos: lectura/escritura de Excel,
  repositorios Supabase, CLI, y (más adelante) la UI Streamlit.
- **`config`**: settings y *wiring* (composición de dependencias / inyección).

### Estructura de carpetas

```
distribuciones-santiago/
├── CLAUDE.md
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

---

## 6. Datos para sembrar Supabase (desde los .xlsm de referencia)

Los archivos `.xlsm` de planeación traen las hojas de las que se siembra la base. **Antes de sembrar,
inspecciona programáticamente las primeras filas de cada hoja para confirmar el orden de columnas** (los
datos son viejos y pueden variar). Mapeo esperado:

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

## 10. Fases del proyecto

1. **Fundación**: esqueleto hexagonal + esquema Supabase + siembra desde Excel.  ← empezar aquí
2. **Ingesta + pivote**: leer el ECOM crudo, normalizar, resolver zona por cliente, pivote por zona.
3. **Clientes nuevos**: asistente que sugiere zona a los #N/D (voto de vecinos por ciudad+barrio).
4. **Balanceador**: reparto de zonas a carros (heurística primero, luego OR-Tools + decisión del carro 16).
5. **UI + exportación**: Streamlit (revisión y ajuste manual con recálculo en vivo) + export ECOM/Excel + histórico.
