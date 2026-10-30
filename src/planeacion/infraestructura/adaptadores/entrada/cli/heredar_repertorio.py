"""Comando `planeacion-heredar-repertorio`: tapa los huecos del repertorio nuevo.

Toma el `salidas/mapeo_zonas_<fecha>.csv` que escribe `planeacion-resincronizar` y,
para cada zona nueva sin repertorio ese día, estima el suyo mezclando el de las
zonas viejas de las que vinieron sus clientes. Ver `herencia.py` para las reglas.

Se corre DESPUÉS de sembrar: lo sembrado con los nombres nuevos manda, y la
herencia solo rellena los días que la siembra no cubrió.
"""

import argparse
import csv
import sys
from datetime import date
from pathlib import Path

from pydantic import ValidationError

from planeacion.config.contenedor import Contenedor, crear_contenedor
from planeacion.config.settings import Settings
from planeacion.domain.modelo import NOMBRES_ESPECIALES, nombre_sin_prefijo
from planeacion.infraestructura.adaptadores.entrada.cli.herencia import (
    Herencia,
    heredar,
    leer_mapeo,
    leer_respaldo,
)
from planeacion.infraestructura.adaptadores.entrada.cli.sembrar_repertorio import (
    respaldar_repertorio,
)

_MAX_EJEMPLOS = 10
# La base los guarda en minúscula; se compara sin tener en cuenta mayúsculas para
# que el orden del reporte sea el de la semana y no el alfabético.
_DIAS = ("lunes", "martes", "miercoles", "jueves", "viernes", "sabado")


def _orden_del_dia(dia: str) -> int:
    """Posición en la semana, o el final si el día no se reconoce."""
    nombre = dia.strip().lower()
    return _DIAS.index(nombre) if nombre in _DIAS else len(_DIAS)


def _nombres_especiales(contenedor: Contenedor) -> list[str]:
    """Las zonas especiales: la marca de la base si existe, el catálogo si no.

    La columna `especial` llega con la migración 007. Mientras no esté aplicada se
    usan los nombres del dominio, así que la herencia nunca le inventa repertorio
    a un cliente especial por el orden del despliegue.
    """
    marcadas = [zona.nombre for zona in contenedor.zonas.listar() if zona.especial]
    return marcadas or list(NOMBRES_ESPECIALES)


def _reportar(herencia: Herencia, especiales: list[str], aplicado: bool) -> None:
    print("=" * 78)
    print(f"HERENCIA DE REPERTORIO ({'aplicada' if aplicado else 'reporte'})")
    print("=" * 78)

    por_dia = herencia.pares_por_dia
    print(f"\nPares heredados: {sum(por_dia.values())}")
    ordenados = sorted(por_dia.items(), key=lambda par: _orden_del_dia(par[0]))
    for dia, cuantos in ordenados:
        fuera = "  (día fuera de lunes-sábado)" if _orden_del_dia(dia) == len(_DIAS) else ""
        print(f"  {dia:<10} {cuantos:>5}{fuera}")

    print(f"\nZonas que reciben herencia: {len({par.nombre_zona for par in herencia.pares})}")
    print(f"Zonas cuyos días ya estaban sembrados (no se tocan): {len(herencia.dias_respetados)}")
    print(f"Zonas especiales ignoradas (no tienen repertorio): {len(herencia.especiales_ignoradas)}")
    for nombre in herencia.especiales_ignoradas:
        print(f"  - {nombre}")
    if len(especiales) == len(NOMBRES_ESPECIALES) and not any(
        nombre_sin_prefijo(nombre).upper() in {n.upper() for n in NOMBRES_ESPECIALES}
        for nombre in herencia.especiales_ignoradas
    ):
        print("  (ninguna zona especial estaba en el mapeo)")

    print(f"\nZonas nuevas que quedan SIN NINGÚN par: {len(herencia.sin_ningun_par)}")
    print("  Sin par no tienen carro elegible: hay que asignarlas a mano en Configuración.")
    for nombre in herencia.sin_ningun_par:
        print(f"  - {nombre}")

    print("\nMuestra de la herencia (10 zonas):")
    por_zona: dict[str, list[str]] = {}
    for par in herencia.pares:
        por_zona.setdefault(par.nombre_zona, []).append(
            f"{par.dia_semana[:3]} carro {par.numero_carro} ×{par.frecuencia}"
        )
    for nombre, detalle in list(sorted(por_zona.items()))[:_MAX_EJEMPLOS]:
        print(f"  {nombre}")
        print(f"      {', '.join(detalle[:8])}{' ...' if len(detalle) > 8 else ''}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Hereda el repertorio de las zonas viejas a las nuevas, según el mapeo de "
        "clientes que escribe planeacion-resincronizar. Corre DESPUÉS de sembrar: "
        "lo sembrado manda y la herencia solo tapa huecos."
    )
    parser.add_argument("ruta_csv", type=Path, help="el salidas/mapeo_zonas_<fecha>.csv")
    parser.add_argument(
        "--aplicar",
        action="store_true",
        help="escribe los pares heredados en Supabase (por defecto solo reporta)",
    )
    parser.add_argument(
        "--desde-respaldo",
        type=Path,
        help="hereda del repertorio guardado en este CSV en vez del que hay en la base. "
        "OBLIGATORIO después de una resiembra con --vaciar: el vaciado borra los pares de "
        "las zonas viejas, que son el origen de la herencia. Es el "
        "salidas/carro_zonas_respaldo_<fecha>.csv que escribe la siembra antes de vaciar.",
    )
    parser.add_argument(
        "--salidas",
        type=Path,
        default=Path("salidas"),
        help="carpeta del respaldo previo (por defecto: salidas/)",
    )
    args = parser.parse_args()

    if not args.ruta_csv.exists():
        print(f"No existe el archivo {args.ruta_csv}", file=sys.stderr)
        return 1
    try:
        contenedor = crear_contenedor(Settings())
    except ValidationError as error:
        print(f"Faltan credenciales de Supabase: {error}", file=sys.stderr)
        return 1

    with args.ruta_csv.open(encoding="utf-8", newline="") as archivo:
        origenes = leer_mapeo(csv.reader(archivo))
    if not origenes:
        print(f"El mapeo {args.ruta_csv} no tiene filas utilizables", file=sys.stderr)
        return 1

    especiales = _nombres_especiales(contenedor)
    # Las frecuencias traen el repertorio completo, incluidas las zonas ya
    # desactivadas: son justamente el origen de la herencia.
    frecuencias = contenedor.carro_zonas.frecuencias()
    del_origen = None
    if args.desde_respaldo is not None:
        if not args.desde_respaldo.exists():
            print(f"No existe el respaldo {args.desde_respaldo}", file=sys.stderr)
            return 1
        with args.desde_respaldo.open(encoding="utf-8", newline="") as archivo:
            del_origen = leer_respaldo(csv.reader(archivo))
        if not del_origen:
            print(f"El respaldo {args.desde_respaldo} no tiene pares utilizables", file=sys.stderr)
            return 1
        print(f"Heredando del respaldo {args.desde_respaldo}: {len(del_origen)} par(es) de origen")
        print(f"Repertorio actual en la base: {len(frecuencias)} par(es) (mandan sobre la herencia)")
    herencia = heredar(origenes, frecuencias, especiales, frecuencias_origen=del_origen)
    _reportar(herencia, especiales, aplicado=False)

    if not args.aplicar:
        print("\nModo reporte: no se escribió nada. Para aplicar: --aplicar")
        return 0
    if not herencia.pares:
        print("\nNo hay nada que heredar.")
        return 0

    # El repertorio es trabajo de configuración de meses y la herencia escribe
    # sobre él: respaldo antes, como en la siembra.
    destino = args.salidas / f"repertorio_antes_de_heredar_{date.today().isoformat()}.csv"
    guardados = respaldar_repertorio(contenedor, destino)
    print(f"\nRespaldo del repertorio actual: {guardados} par(es) en {destino}")
    escritos = contenedor.carro_zonas.asignar_lote(herencia.pares)
    print(f"Pares heredados escritos: {escritos}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
