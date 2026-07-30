"""Siembra del repertorio de zonas por carro desde las hojas PLANEACION históricas.

Uso:
    uv run planeacion-sembrar-repertorio datos/*.xlsm
    uv run planeacion-sembrar-repertorio "datos/DEL_24_PAR_EL_26_JUNIO.xlsm" ...

Lee los pares (carro, zona) de la hoja PLANEACION de cada .xlsm (col A = carro,
col B = zona) y los agrega a la tabla carro_zonas (upsert idempotente: re-correr
no duplica). Los números de carro del histórico son las rutas 1-18 que coinciden
con carros.numero; se reporta cualquier carro o zona que no case con la base.
"""

import argparse
import sys
from pathlib import Path

from pydantic import ValidationError

from planeacion.config.contenedor import Contenedor, crear_contenedor
from planeacion.config.settings import Settings
from planeacion.domain.servicios.parseo_zonas import normalizar_nombre_zona
from planeacion.infraestructura.adaptadores.salida.excel.lector_referencia import (
    HOJA_PLANEACION,
    LectorReferenciaExcel,
)


def cruzar_pares(
    pares: set[tuple[str, str]],
    numeros_carros: set[str],
    nombres_zonas: set[str],
) -> tuple[set[tuple[str, str]], set[str], set[str]]:
    """Separa los pares que casan con la base de los carros/zonas desconocidos."""
    validos = {(c, z) for c, z in pares if c in numeros_carros and z in nombres_zonas}
    carros_desconocidos = {c for c, _ in pares if c not in numeros_carros}
    zonas_desconocidas = {z for _, z in pares if z not in nombres_zonas}
    return validos, carros_desconocidos, zonas_desconocidas


def _expandir_rutas(patrones: list[str]) -> list[Path]:
    """Expande globs (PowerShell/cmd no lo hacen solos) y deduplica preservando orden."""
    rutas: list[Path] = []
    for patron in patrones:
        if "*" in patron or "?" in patron:
            encontradas = sorted(Path().glob(patron))
            if not encontradas:
                print(f"AVISO: el patrón {patron!r} no casa con ningún archivo.", file=sys.stderr)
            rutas.extend(encontradas)
        else:
            rutas.append(Path(patron))
    return list(dict.fromkeys(rutas))


def _leer_pares(rutas: list[Path]) -> set[tuple[str, str]]:
    pares: set[tuple[str, str]] = set()
    for ruta in rutas:
        with LectorReferenciaExcel(ruta) as lector:
            if not lector.tiene_hoja(HOJA_PLANEACION):
                print(f"AVISO: {ruta.name} no tiene hoja {HOJA_PLANEACION}; se salta.", file=sys.stderr)
                continue
            del_archivo = {
                (fila.carro, normalizar_nombre_zona(fila.zona))
                for fila in lector.leer_asignaciones_planeacion()
            }
        print(f"  {ruta.name}: {len(del_archivo)} pares (carro, zona)")
        pares |= del_archivo
    return pares


def _reportar(contenedor: Contenedor) -> None:
    repertorio = contenedor.carro_zonas.obtener_todos()
    print("\nRepertorio resultante por carro:")
    carros = sorted(contenedor.carros.listar(), key=lambda c: (len(c.numero), c.numero))
    for carro in carros:
        zonas = repertorio.get(carro.numero, set())
        marca = "" if zonas else "  <- sin configurar"
        conductor = carro.conductor or "sin conductor"
        print(f"  carro {carro.numero:>2} ({conductor}): {len(zonas)} zonas{marca}")

    con_carro = {zona for zonas in repertorio.values() for zona in zonas}
    activas = [zona.nombre for zona in contenedor.zonas.listar() if zona.activa]
    sin_carro = [nombre for nombre in activas if nombre not in con_carro]
    print(
        f"\nZonas activas sin ningún carro: {len(sin_carro)} de {len(activas)} "
        "(configurables en la UI: Configuración > Zonas por carro)."
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Siembra la tabla carro_zonas desde las hojas PLANEACION de .xlsm históricos."
    )
    parser.add_argument("rutas", nargs="+", help="rutas (o globs) de los .xlsm de planeación")
    args = parser.parse_args()

    rutas = _expandir_rutas(args.rutas)
    faltantes = [ruta for ruta in rutas if not ruta.exists()]
    if faltantes:
        print(f"ERROR: no existen: {', '.join(str(r) for r in faltantes)}", file=sys.stderr)
        return 1
    if not rutas:
        print("ERROR: ningún archivo para leer.", file=sys.stderr)
        return 1

    try:
        settings = Settings()
    except ValidationError:
        print(
            "ERROR: faltan SUPABASE_URL / SUPABASE_KEY. Copia .env.example a .env "
            "y pon las credenciales del proyecto (usa la clave service_role).",
            file=sys.stderr,
        )
        return 1

    print(f"Leyendo la hoja {HOJA_PLANEACION} de {len(rutas)} archivo(s)...")
    pares = _leer_pares(rutas)
    if not pares:
        print("ERROR: no se encontró ningún par (carro, zona).", file=sys.stderr)
        return 1

    contenedor = crear_contenedor(settings)
    numeros_carros = {carro.numero for carro in contenedor.carros.listar()}
    nombres_zonas = {zona.nombre for zona in contenedor.zonas.listar()}
    validos, carros_desconocidos, zonas_desconocidas = cruzar_pares(pares, numeros_carros, nombres_zonas)

    print(f"\nPares distintos en el histórico: {len(pares)}")
    if carros_desconocidos:
        numeros = ", ".join(sorted(carros_desconocidos, key=lambda n: (len(n), n)))
        print(f"AVISO: carros del histórico que NO están en la base (se saltan): {numeros}")
    if zonas_desconocidas:
        print("AVISO: zonas del histórico que NO casan con zonas.nombre (se saltan):")
        for zona in sorted(zonas_desconocidas):
            print(f"  - {zona}")

    existentes = {
        (numero, zona) for numero, zonas in contenedor.carro_zonas.obtener_todos().items() for zona in zonas
    }
    nuevos = validos - existentes
    contenedor.carro_zonas.asignar_lote(sorted(validos))
    print(f"Pares sembrados: {len(validos)} ({len(nuevos)} nuevos, {len(validos) - len(nuevos)} ya existían)")

    _reportar(contenedor)
    return 0


if __name__ == "__main__":
    sys.exit(main())
