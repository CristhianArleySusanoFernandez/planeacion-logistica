# Mapeo vehículos físicos ↔ rutas de reparto

> **Documento de referencia, mantenido a mano** (última revisión: julio de 2026).
> El cruce se construyó una sola vez con un lector del bloque 1 de la hoja `BASE`
> que **ya no existe en el código**: se eliminó en la limpieza final porque el
> bloque 1 no se siembra y ningún caso de uso lo consumía. Esta tabla no se
> regenera sola; para corregirla o completarla hay que editarla acá (ver "Cómo
> completarlo" al final).

La hoja `BASE` de los `.xlsm` de planeación tiene **dos tablas**:

- **Bloque 1** (filas 1–22): catálogo de **vehículos físicos** — `Codigo` (108, 820, 127...),
  conductor, placa, auxiliar y una "zona base". **No se siembra**: es solo referencia.
- **Bloque 2** (desde la fila-encabezado `Ruta | Facturas | Clientes | Pesos | Kilos |
  CONDUCTOR | AUX | CIUDAD`): las **rutas de reparto 1..18**. Esta es la numeración que usan
  Rudy y facturación, y es la que se siembra en la tabla `carros` de Supabase
  (`planeacion-sembrar`). La ruta **16** es el carro externo contratado ($160.000/día) y la
  **18** es un refuerzo esporádico (en la semana del 19–22 de junio de 2026 salió con 2
  facturas de Miraflores); se siembra como `activo = false` salvo que facture.

## El cruce (vínculo: conductor, reforzado con auxiliar y zona)

Construido comparando `DEL_24_PAR_EL_26_JUNIO.xlsm` y `DEL_19_PAR_EL_22_JUNIO.xlsm`.
Solo las rutas con confianza **✅ alta** llevan la placa copiada en la tabla `carros`
(constante `_PLACAS_POR_RUTA` en `sembrar.py`); las dudosas quedan sin placa a propósito.

| Ruta | Conductor (bloque 2) | Vehículo físico | Placa | Confianza | Evidencia |
|---|---|---|---|---|---|
| 1 | FABIAN | 820 · FABIAN CAÑON | SZN374 | ✅ alta | conductor |
| 2 | JUAN PABLO | ¿986 · ANGELICA? | JPO376 | ⚠️ baja | solo la zona (CHIQUIN RUTA 1 NORTE) |
| 3 | DAVID GONZALEZ | — | — | ✗ sin vínculo | |
| 4 | SEBASTIAN | 455 · JESSICA VELASCO | JPO452 | ✅ alta | auxiliar EDGAR COBARIA + zona VELEZ |
| 5 | ANGEL BAREÑO | ¿593 · OCTAVIO BRITO? | JPO402 | ⚠️ baja | zona parcial (BARBOSA-PUENTE) |
| 6 | CAMILO SOTELO | ¿108 · ESTEBAN ROMERO? | LTL380 | ⚠️ baja | solo la zona (RUTA MUZO) |
| 7 | CESAR DAZA | 549 · ESTEBAN DAZA | XID522 | ✅ alta | apellido DAZA + zona RUTA FLORIAN |
| 8 | JUAN ARAQUE | 592 · JUAN ARAQUE | KSK090 | ✅ alta | conductor + ciudad GARAGOA |
| 9 | GILBERTO | 335 · GILBERTO | LTL370 | ✅ alta | conductor |
| 10 | RAUL | s/código · RAUL ("PLATAFORMA") | TUF536 | ✅ alta | conductor |
| 11 | JAIRO GARZON / CRISTIAN LOPEZ | — | — | ✗ sin vínculo | (el conductor cambió entre semanas) |
| 12 | CARLOS | ¿214 · NANCY JEREZ? | JPO443 | ⚠️ baja | zona parcial (RUTA OCCIDENTE, semana 19–22) |
| 13 | YOVANNY SA | 550 · YOVANY SALAMANCA | JPO511 | ✅ alta | conductor + auxiliar OLGA |
| 14 | LUIS EDUARDO | 373 · CAMILO PACHECO | JPO388 | ✅ alta | auxiliar LAURA RIOS + zona RUTA CENTRO 1 |
| 15 | JOSE JIMENEZ | ¿100 · NESTOR INFANTE? | TAP025 | ⚠️ baja | zona parcial (PATRIOTAS) |
| 16 | JOSE LUIS | ¿3 · YEISON SUAREZ? | JPO418 | ⚠️ baja | zona (ARCABUCO-MOTAVITA); ERIKA es aux del 203 |
| 17 | MAURICIO JIMENEZ | ¿203 · ALEXANDER SAENZ? | JPO419 | ⚠️ baja | zona parcial (LIBERTADOR-BOLIVAR PARAISO) |
| 18 | GILBERTO (semana 19–22) | 335 · GILBERTO | LTL370 | ⚠️ baja | mismo conductor que la ruta 9 (refuerzo) |

## Vehículos físicos sin ruta segura

100 (NESTOR INFANTE), 112 (HOLLMAN), 127 (JIMMY CAÑON), 214 (NANCY JEREZ),
451 (FREDY PEÑA), 593 (OCTAVIO BRITO), 776 (ALEJANDRO CELY), 931 (LUIS RUIZ).

## Cómo completarlo

La fuente definitiva es **preguntarle a Rudy** qué placa sale por cada ruta. Cuando se
confirme un cruce, agregarlo a `_PLACAS_POR_RUTA` en
`src/planeacion/infraestructura/adaptadores/entrada/cli/sembrar.py` (o editar la placa
directamente en la página ⚙ Configuración de la app) y actualizar esta tabla.
