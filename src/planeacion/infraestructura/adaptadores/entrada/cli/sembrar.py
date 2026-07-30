"""Comando de siembra: puebla Supabase desde el .xlsm de planeación de referencia.

Uso:
    uv run planeacion-sembrar datos/DEL_24_PAR_EL_26_JUNIO.xlsm
    uv run planeacion-sembrar datos/DEL_24_PAR_EL_26_JUNIO.xlsm --solo-inspeccion

Primero imprime el mapeo de columnas detectado en cada hoja (para verificarlo a
ojo), valida los encabezados y luego siembra en orden: municipios → zonas →
carros → clientes → correcciones → overrides. Es idempotente: re-sembrar no
duplica registros.
"""

import argparse
import sys
from decimal import Decimal
from pathlib import Path

from pydantic import ValidationError

from planeacion.config.contenedor import Contenedor, crear_contenedor
from planeacion.config.settings import Settings
from planeacion.domain.modelo import (
    MUNICIPIO_OTROS,
    Carro,
    Cliente,
    CorreccionUbicacion,
    Municipio,
    OverrideZona,
    Zona,
)
from planeacion.domain.servicios.parseo_zonas import crear_zona, normalizar_nombre_zona
from planeacion.infraestructura.adaptadores.salida.excel.lector_referencia import (
    HOJA_BASE,
    HOJA_CAMBIOS,
    HOJA_MAESTRA,
    HOJA_OVERRIDES,
    FilaCambio,
    FilaMaestra,
    FilaOverride,
    FilaRutaBase,
    LectorReferenciaExcel,
)

_MAPEO_DECLARADO = {
    HOJA_MAESTRA: "A=Codigo  B=Direccion  C=Codigo_Postal  D=Ciudad  E=Barrio  F=RUTA (zona)",
    HOJA_CAMBIOS: "A=Codigo  F=Ciudad Real  G=Barrio Real",
    HOJA_OVERRIDES: "A=Codigo  H=Zona forzada (sin encabezado)",
    HOJA_BASE: "bloque 2 (desde la fila 'Ruta'): A=Ruta  B=Facturas  F=CONDUCTOR  G=AUX  H=CIUDAD",
}

# Rutas de reparto (bloque 2 de BASE): la flota son las rutas fijas 1..18. La 18
# es un refuerzo esporádico, se siembra siempre pero solo queda activa si
# facturó en el archivo de referencia. Rutas mayores solo entran si facturaron.
_MAX_RUTA_FIJA = 18
_RUTA_EXTERNA = "16"  # el carro contratado: $160.000/día
_COSTO_RUTA_EXTERNA = Decimal("160000")

# Vínculo ruta ↔ vehículo físico (bloque 1 de BASE) confirmado por conductor o
# auxiliar; ver docs/mapeo-vehiculos-rutas.md. Solo se copia la placa segura,
# las rutas con cruce dudoso quedan sin placa a propósito.
_PLACAS_POR_RUTA = {
    "1": "SZN374",
    "4": "JPO452",
    "7": "XID522",
    "8": "KSK090",
    "9": "LTL370",
    "10": "TUF536",
    "13": "JPO511",
    "14": "JPO388",
}

_MUNICIPIOS_DE_CIUDAD = ("BARBOSA", "CHIQUINQUIRA", "TUNJA")


def _municipio_de_ciudad(ciudad: str | None) -> Municipio:
    """CIUDAD del bloque 2 → municipio. Lo que no es cabecera propia (MUZO,
    FLORIAN, GARAGOA, MIRAFLORES, VILLA DELEYVA...) cae en OTROS."""
    texto = (ciudad or "").upper()
    for nombre in _MUNICIPIOS_DE_CIUDAD:
        if nombre in texto:
            return Municipio(nombre=nombre)
    return Municipio(nombre=MUNICIPIO_OTROS)


def _construir_carros(rutas_crudas: list[FilaRutaBase]) -> list[Carro]:
    carros: list[Carro] = []
    for fila in rutas_crudas:
        if int(fila.numero) > _MAX_RUTA_FIJA and fila.facturas == 0:
            continue
        es_externa = fila.numero == _RUTA_EXTERNA
        carros.append(
            Carro(
                numero=fila.numero,
                conductor=fila.conductor,
                placa=_PLACAS_POR_RUTA.get(fila.numero),
                auxiliar=fila.auxiliar,
                municipio=_municipio_de_ciudad(fila.ciudad),
                es_externo=es_externa,
                costo_diario=_COSTO_RUTA_EXTERNA if es_externa else Decimal("0"),
                activo=fila.facturas > 0,
            )
        )
    return carros


def _imprimir_inspeccion(lector: LectorReferenciaExcel) -> None:
    print("=" * 78)
    print("INSPECCION DE HOJAS (verifica el mapeo antes de confiar en la siembra)")
    print("=" * 78)
    for hoja, mapeo in _MAPEO_DECLARADO.items():
        print(f"\n[{hoja}]  mapeo detectado: {mapeo}")
        for numero, fila in enumerate(lector.primeras_filas(hoja), 1):
            celdas = "  |  ".join(celda[:22] for celda in fila)
            print(f"  fila {numero}: {celdas}")


class DatosDeSiembra:
    """Los modelos de dominio ya construidos desde el Excel, más lo no mapeable."""

    def __init__(self) -> None:
        self.municipios: list[Municipio] = []
        self.zonas: list[Zona] = []
        self.carros: list[Carro] = []
        self.clientes: list[Cliente] = []
        self.correcciones: list[CorreccionUbicacion] = []
        self.overrides: list[OverrideZona] = []
        self.clientes_sin_zona = 0
        self.clientes_duplicados = 0
        self.overrides_duplicados = 0
        self.zonas_solo_de_overrides: list[str] = []


def _construir_datos(
    maestra: list[FilaMaestra],
    cambios: list[FilaCambio],
    overrides_crudos: list[FilaOverride],
    rutas_crudas: list[FilaRutaBase],
) -> DatosDeSiembra:
    datos = DatosDeSiembra()

    # Zonas: los valores distintos de RUTA en la maestra (normalizados) más las
    # zonas que solo aparecen forzadas en "martha ojo" (deben existir para la FK).
    zonas_por_nombre: dict[str, Zona] = {}
    for fila in maestra:
        if fila.ruta:
            nombre = normalizar_nombre_zona(fila.ruta)
            if nombre not in zonas_por_nombre:
                zonas_por_nombre[nombre] = crear_zona(nombre)
    for override in overrides_crudos:
        nombre = normalizar_nombre_zona(override.zona)
        if nombre not in zonas_por_nombre:
            zonas_por_nombre[nombre] = crear_zona(nombre)
            datos.zonas_solo_de_overrides.append(nombre)
    datos.zonas = list(zonas_por_nombre.values())

    # Carros: bloque 2 de la hoja BASE (las rutas de reparto 1..18, que es lo
    # que usan Rudy y facturación). El bloque 1 (vehículos físicos) NO se
    # siembra; el cruce entre ambos vive en docs/mapeo-vehiculos-rutas.md.
    datos.carros = _construir_carros(rutas_crudas)

    # Municipios: los de las zonas, los de los carros y siempre OTROS.
    nombres_municipios = {zona.municipio.nombre for zona in datos.zonas}
    nombres_municipios.update(c.municipio.nombre for c in datos.carros if c.municipio)
    nombres_municipios.add(MUNICIPIO_OTROS)
    datos.municipios = [Municipio(nombre=n) for n in sorted(nombres_municipios)]

    # Clientes: la maestra trae códigos repetidos; gana la primera aparición
    # (mismo criterio que BUSCARV en el Excel original).
    vistos: set[str] = set()
    for fila in maestra:
        if fila.codigo in vistos:
            datos.clientes_duplicados += 1
            continue
        vistos.add(fila.codigo)
        zona = zonas_por_nombre.get(normalizar_nombre_zona(fila.ruta)) if fila.ruta else None
        if zona is None:
            datos.clientes_sin_zona += 1
        datos.clientes.append(
            Cliente(
                codigo=fila.codigo,
                direccion=fila.direccion,
                barrio=fila.barrio,
                ciudad=fila.ciudad,
                zona=zona,
            )
        )

    codigos_corregidos: set[str] = set()
    for fila_cambio in cambios:
        if fila_cambio.codigo in codigos_corregidos:
            continue
        codigos_corregidos.add(fila_cambio.codigo)
        datos.correcciones.append(
            CorreccionUbicacion(
                cliente_codigo=fila_cambio.codigo,
                ciudad_real=fila_cambio.ciudad_real,
                barrio_real=fila_cambio.barrio_real,
            )
        )

    codigos_forzados: set[str] = set()
    for override in overrides_crudos:
        if override.codigo in codigos_forzados:
            datos.overrides_duplicados += 1
            continue
        codigos_forzados.add(override.codigo)
        datos.overrides.append(
            OverrideZona(
                cliente_codigo=override.codigo,
                zona_nombre=normalizar_nombre_zona(override.zona),
            )
        )

    return datos


def _imprimir_resumen_construccion(datos: DatosDeSiembra) -> None:
    print("\n" + "=" * 78)
    print("DATOS CONSTRUIDOS DESDE EL EXCEL")
    print("=" * 78)
    municipios_de_zonas = {z.municipio.nombre for z in datos.zonas}
    conteo_por_municipio = {
        m: sum(1 for z in datos.zonas if z.municipio.nombre == m) for m in sorted(municipios_de_zonas)
    }
    print(f"  municipios: {len(datos.municipios)} -> {', '.join(m.nombre for m in datos.municipios)}")
    print(f"  zonas: {len(datos.zonas)} -> {conteo_por_municipio}")
    activos = sum(1 for c in datos.carros if c.activo)
    print(
        f"  carros (rutas del bloque 2 de BASE): {len(datos.carros)} "
        f"(activos: {activos}, externos: {sum(1 for c in datos.carros if c.es_externo)})"
    )
    print(
        f"  clientes: {len(datos.clientes)} "
        f"(duplicados omitidos: {datos.clientes_duplicados}, sin zona: {datos.clientes_sin_zona})"
    )
    print(f"  correcciones_ubicacion: {len(datos.correcciones)}")
    print(f"  overrides_zona: {len(datos.overrides)} (duplicados omitidos: {datos.overrides_duplicados})")
    if datos.zonas_solo_de_overrides:
        print(f"  zonas que solo existen en 'martha ojo': {datos.zonas_solo_de_overrides}")


def _sembrar(contenedor: Contenedor, datos: DatosDeSiembra) -> None:
    print("\n" + "=" * 78)
    print("SIEMBRA EN SUPABASE")
    print("=" * 78)
    ids_municipios = contenedor.municipios.guardar_lote(datos.municipios)
    print(f"  municipios sembrados: {len(ids_municipios)}")
    ids_zonas = contenedor.zonas.guardar_lote(datos.zonas, ids_municipios)
    print(f"  zonas sembradas: {len(datos.zonas)} (en tabla: {len(ids_zonas)})")
    n_carros = contenedor.carros.guardar_lote(datos.carros, ids_municipios)
    print(f"  carros sembrados: {n_carros}")
    n_clientes = contenedor.clientes.guardar_lote(datos.clientes, ids_zonas)
    print(f"  clientes sembrados: {n_clientes} (en tabla: {contenedor.clientes.contar()})")
    n_correcciones = contenedor.correcciones.guardar_lote(datos.correcciones)
    print(f"  correcciones sembradas: {n_correcciones}")

    con_zona = [o for o in datos.overrides if o.zona_nombre in ids_zonas]
    sin_zona = len(datos.overrides) - len(con_zona)
    n_overrides = contenedor.overrides.guardar_lote(con_zona, ids_zonas)
    print(f"  overrides sembrados: {n_overrides}" + (f" (sin zona casable: {sin_zona})" if sin_zona else ""))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Siembra Supabase desde el .xlsm de planeación de referencia."
    )
    parser.add_argument("ruta_xlsm", type=Path, help="ruta del .xlsm (hojas MAESTRA/CAMBIOS/martha ojo/BASE)")
    parser.add_argument(
        "--solo-inspeccion",
        action="store_true",
        help="imprime el mapeo y los conteos sin escribir en Supabase",
    )
    args = parser.parse_args()

    if not args.ruta_xlsm.exists():
        print(f"ERROR: no existe el archivo {args.ruta_xlsm}", file=sys.stderr)
        return 1

    print(f"Leyendo {args.ruta_xlsm} (read_only)...")
    with LectorReferenciaExcel(args.ruta_xlsm) as lector:
        faltantes = lector.hojas_faltantes()
        if faltantes:
            print(f"ERROR: al archivo le faltan las hojas {faltantes}", file=sys.stderr)
            return 1

        _imprimir_inspeccion(lector)

        errores = lector.errores_de_encabezado()
        if errores:
            print("\nERROR: los encabezados no calzan con el mapeo esperado:", file=sys.stderr)
            for error in errores:
                print(f"  - {error}", file=sys.stderr)
            print("Corrige el mapeo en lector_referencia.py antes de sembrar.", file=sys.stderr)
            return 1

        rutas_crudas = list(lector.leer_rutas())
        if not rutas_crudas:
            print(
                "\nERROR: no se encontró el bloque 2 de la hoja BASE (la fila-encabezado "
                "'Ruta | Facturas | ...'). Sin rutas no hay flota que sembrar.",
                file=sys.stderr,
            )
            return 1

        datos = _construir_datos(
            maestra=list(lector.leer_maestra()),
            cambios=list(lector.leer_cambios()),
            overrides_crudos=list(lector.leer_overrides()),
            rutas_crudas=rutas_crudas,
        )

    _imprimir_resumen_construccion(datos)

    if args.solo_inspeccion:
        print("\n--solo-inspeccion: no se escribió nada en Supabase.")
        return 0

    try:
        settings = Settings()
    except ValidationError:
        sys.stdout.flush()
        print(
            "\nERROR: faltan SUPABASE_URL / SUPABASE_KEY. Copia .env.example a .env "
            "y pon las credenciales del proyecto (usa la clave service_role).",
            file=sys.stderr,
        )
        return 1

    _sembrar(crear_contenedor(settings), datos)
    print("\nSiembra terminada.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
