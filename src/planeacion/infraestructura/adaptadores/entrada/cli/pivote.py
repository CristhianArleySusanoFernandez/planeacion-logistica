"""Comando de pivote: lee el ECOM crudo del día y muestra el pivote por zona.

Uso:
    uv run planeacion-pivote datos/pedidos24-26Junio.xlsx
    uv run planeacion-pivote datos/pedidos24-26Junio.xlsx --fecha 2026-06-24 --exportar-csv pivote.csv

Sin --fecha se pivotea la fecha válida más frecuente del archivo; los pedidos de
otras fechas (o con fecha ilegible) se reportan como excluidos, no se pierden.
"""

import argparse
import csv
import sys
from datetime import date
from pathlib import Path

from pydantic import ValidationError

from planeacion.application.dto.pivote import PivotePorZonaDTO
from planeacion.config.contenedor import crear_contenedor, crear_generar_pivote
from planeacion.config.settings import Settings
from planeacion.domain.errores import ErrorDeDominio
from planeacion.infraestructura.adaptadores.salida.excel.lector_ecom import FormatoEcomInvalido

_ANCHO_ZONA = 52
_MOTIVOS = {
    "NO_ESTA_EN_MAESTRA": "no está en la maestra (#N/D)",
    "EN_MAESTRA_SIN_ZONA": "en la maestra pero sin zona",
}


def _fila(zona: str, facturas: object, clientes: object, pesos: object, kilos: object) -> str:
    return f"  {zona:<{_ANCHO_ZONA}} {facturas:>8} {clientes:>8} {pesos:>16} {kilos:>10}"


def _imprimir_pivote(pivote: PivotePorZonaDTO) -> None:
    print("=" * 100)
    print(f"PIVOTE POR ZONA — {pivote.fecha.isoformat()}")
    print("=" * 100)

    municipio_actual: str | None = None
    for zona in pivote.zonas:
        if zona.municipio != municipio_actual:
            if municipio_actual is not None:
                _imprimir_subtotal(pivote, municipio_actual)
            municipio_actual = zona.municipio
            print(f"\n[{municipio_actual}]")
            print(_fila("zona", "facturas", "clientes", "pesos", "kilos"))
        print(
            _fila(
                zona.zona[:_ANCHO_ZONA],
                zona.facturas,
                zona.clientes,
                f"{zona.pesos:,.2f}",
                f"{zona.kilos:,.2f}",
            )
        )
    if municipio_actual is not None:
        _imprimir_subtotal(pivote, municipio_actual)

    print("\n" + "-" * 100)
    print(
        _fila(
            "TOTAL GENERAL",
            pivote.total_facturas,
            pivote.total_clientes,
            f"{pivote.total_pesos:,.2f}",
            f"{pivote.total_kilos:,.2f}",
        )
    )

    if pivote.no_resueltos:
        print(f"\nCLIENTES SIN ZONA ({len(pivote.no_resueltos)}) — "
              f"{pivote.facturas_no_resueltas} facturas, "
              f"${pivote.pesos_no_resueltos:,.2f}, {pivote.kilos_no_resueltos:,.2f} kg "
              "(incluidos en el total general):")
        for cliente in pivote.no_resueltos:
            detalle = " / ".join(p for p in (cliente.nombre, cliente.ciudad, cliente.barrio) if p)
            motivo = _MOTIVOS.get(cliente.motivo, cliente.motivo)
            print(f"  {cliente.codigo:<10} {detalle}  [{motivo}]")
    else:
        print("\nClientes sin zona: 0")

    if pivote.pedidos_excluidos_por_fecha:
        print(
            f"\nOJO: {pivote.pedidos_excluidos_por_fecha} pedidos del archivo NO son del "
            f"{pivote.fecha.isoformat()} y quedaron fuera del pivote "
            f"(fechas: {', '.join(pivote.fechas_excluidas)})."
        )


def _imprimir_subtotal(pivote: PivotePorZonaDTO, municipio: str) -> None:
    zonas = [z for z in pivote.zonas if z.municipio == municipio]
    print(
        _fila(
            f"subtotal {municipio}",
            sum(z.facturas for z in zonas),
            sum(z.clientes for z in zonas),
            f"{sum(z.pesos for z in zonas):,.2f}",
            f"{sum(z.kilos for z in zonas):,.2f}",
        )
    )


def _exportar_csv(pivote: PivotePorZonaDTO, ruta: Path) -> None:
    # utf-8-sig para que Excel en Windows abra las tildes bien.
    with ruta.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.writer(archivo, delimiter=";")
        escritor.writerow(["municipio", "zona", "facturas", "clientes", "pesos", "kilos"])
        for zona in pivote.zonas:
            escritor.writerow(
                [zona.municipio, zona.zona, zona.facturas, zona.clientes, zona.pesos, zona.kilos]
            )
        if pivote.no_resueltos:
            escritor.writerow(
                [
                    "",
                    "SIN ZONA",
                    pivote.facturas_no_resueltas,
                    len(pivote.no_resueltos),
                    pivote.pesos_no_resueltos,
                    pivote.kilos_no_resueltos,
                ]
            )
        escritor.writerow(
            [
                "",
                "TOTAL GENERAL",
                pivote.total_facturas,
                pivote.total_clientes,
                pivote.total_pesos,
                pivote.total_kilos,
            ]
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Genera el pivote por zona desde el ECOM crudo del día."
    )
    parser.add_argument("ruta_ecom", type=Path, help="ruta del .xlsx crudo de ECOM (hoja Hoja1)")
    parser.add_argument(
        "--fecha",
        type=date.fromisoformat,
        default=None,
        help="fecha a pivotear (AAAA-MM-DD); sin ella se usa la más frecuente del archivo",
    )
    parser.add_argument(
        "--exportar-csv",
        type=Path,
        default=None,
        metavar="RUTA_CSV",
        help="además de imprimir, escribe el pivote en un CSV (separado por ';')",
    )
    args = parser.parse_args()

    if not args.ruta_ecom.exists():
        print(f"ERROR: no existe el archivo {args.ruta_ecom}", file=sys.stderr)
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

    caso_uso = crear_generar_pivote(crear_contenedor(settings))
    print(f"Leyendo {args.ruta_ecom} y resolviendo zonas contra Supabase...")
    try:
        pivote = caso_uso.ejecutar(args.ruta_ecom, fecha=args.fecha)
    except (ErrorDeDominio, FormatoEcomInvalido) as error:
        sys.stdout.flush()
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    _imprimir_pivote(pivote)

    if args.exportar_csv is not None:
        _exportar_csv(pivote, args.exportar_csv)
        print(f"\nPivote exportado a {args.exportar_csv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
