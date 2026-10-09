"""Comando de medición: cuánto tarda cada etapa del flujo y cuántas consultas hace.

Uso:
    uv run planeacion-medir "datos/infpedidos202610070.27834700.xls"
    uv run planeacion-medir "datos/..." --corridas 2 --exportar

Existe por la regla del Prompt 21: **medir antes de optimizar**. "La app se
siente lenta" no se puede trabajar; una tabla de etapas sí.

Corre el flujo entero —contenedor, lectura del ECOM, maestra, pivote, repertorio,
balanceo y exportación— en un mismo proceso y repite, para separar lo que cuesta
la primera vez (conexión TLS a Supabase, import de openpyxl, cachés frías) de lo
que cuesta siempre. Los tiempos salen de ``instrumentacion.medir``, que ya está
puesto en los casos de uso, y las consultas de un envoltorio que cuenta los
viajes a PostgREST en vez de estimarlos.
"""

import argparse
import logging
import sys
import tempfile
from collections import Counter
from pathlib import Path
from time import perf_counter

from pydantic import ValidationError

from planeacion.config.contenedor import (
    Contenedor,
    crear_cliente_supabase,
    crear_contenedor,
    crear_exportador_planeacion,
    crear_generar_planeacion,
)
from planeacion.config.settings import Settings
from planeacion.domain.modelo import Parametros
from planeacion.infraestructura.adaptadores.salida.supabase.cliente_contado import ClienteContado
from planeacion.instrumentacion import RecolectorDeEtapas


def _imprimir_etapas(etapas: list[tuple[str, float]], total: float) -> None:
    print(f"\n{'etapa':<34} {'segundos':>9} {'% del total':>12}")
    print("-" * 58)
    for etapa, segundos in etapas:
        porcentaje = segundos / total if total else 0
        print(f"{etapa[:34]:<34} {segundos:9.3f} {porcentaje:12.1%}")
    print("-" * 58)
    medido = sum(segundos for _, segundos in etapas)
    print(f"{'suma de las etapas medidas':<34} {medido:9.3f} {medido / total if total else 0:12.1%}")
    print(f"{'TOTAL de la corrida':<34} {total:9.3f}")


def _imprimir_consultas(consultas: Counter[str]) -> None:
    print(f"\n{'tabla':<28} {'consultas':>9}")
    print("-" * 40)
    for tabla, veces in consultas.most_common():
        print(f"{tabla[:28]:<28} {veces:9d}")
    print("-" * 40)
    print(f"{'TOTAL de viajes a Supabase':<28} {sum(consultas.values()):9d}")


def _una_corrida(
    contenedor: Contenedor,
    cliente: ClienteContado,
    ruta_ecom: Path,
    recolector: RecolectorDeEtapas,
    exportar: bool,
) -> tuple[list[tuple[str, float]], float, Counter[str]]:
    recolector.limpiar()
    antes = cliente.foto()
    inicio = perf_counter()

    planeacion = crear_generar_planeacion(contenedor).ejecutar(ruta_ecom, usar_historico=True)
    if exportar:
        destino = Path(tempfile.gettempdir()) / "medicion.xlsx"
        parametros = Parametros(valores=contenedor.parametros.obtener())
        crear_exportador_planeacion().exportar(planeacion, destino, parametros)

    total = perf_counter() - inicio
    # El resumen del día: sirve para comprobar que las dos corridas y las
    # mediciones de antes y después del cambio están mirando lo mismo.
    print(
        f"  resultado: {planeacion.total_facturas} facturas | {planeacion.total_clientes} clientes "
        f"| ${planeacion.total_pesos:,.2f} | {planeacion.total_kilos:,.2f} kg "
        f"| {len(planeacion.asignaciones())} zonas asignadas"
    )
    return list(recolector.etapas), total, cliente.desde(antes)


def main() -> int:
    parser = argparse.ArgumentParser(description="Mide el flujo completo de planeación por etapas.")
    parser.add_argument("ruta_ecom", type=Path, help="el .xls/.xlsx de ECOM del día")
    parser.add_argument(
        "--corridas",
        type=int,
        default=2,
        help="cuántas veces correr el flujo en el mismo proceso (default 2: primera y siguientes)",
    )
    parser.add_argument(
        "--exportar", action="store_true", help="incluye la exportación del Excel en la medición"
    )
    args = parser.parse_args()

    if not args.ruta_ecom.exists():
        print(f"No existe el archivo {args.ruta_ecom}", file=sys.stderr)
        return 1

    recolector = RecolectorDeEtapas()
    logging.getLogger("planeacion").addHandler(recolector)
    logging.getLogger("planeacion").setLevel(logging.INFO)

    try:
        settings = Settings()
    except ValidationError as error:
        print(f"Faltan credenciales de Supabase: {error}", file=sys.stderr)
        return 1

    print("=" * 58)
    print("CONTENEDOR (wiring + primera consulta a Supabase)")
    print("=" * 58)
    inicio = perf_counter()
    cliente = ClienteContado(crear_cliente_supabase(settings))
    contenedor = crear_contenedor(settings, cliente=cliente)
    cableado = perf_counter() - inicio
    inicio = perf_counter()
    municipios = contenedor.municipios.listar()
    primera = perf_counter() - inicio
    print(f"  wiring (sin tocar la red): {cableado:.3f} s")
    print(f"  primera consulta ({len(municipios)} municipios): {primera:.3f} s")

    for numero in range(1, args.corridas + 1):
        print("\n" + "=" * 58)
        print(f"CORRIDA {numero} de {args.corridas}")
        print("=" * 58)
        etapas, total, consultas = _una_corrida(
            contenedor, cliente, args.ruta_ecom, recolector, args.exportar
        )
        _imprimir_etapas(etapas, total)
        _imprimir_consultas(consultas)

    print(f"\nViajes a Supabase en todo el proceso: {cliente.total}")
    return 0
