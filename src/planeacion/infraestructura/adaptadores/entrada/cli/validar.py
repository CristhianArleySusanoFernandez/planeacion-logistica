"""Comando de validación: qué tan cerca queda la propuesta de la planeación manual.

Uso:
    uv run planeacion-validar "datos/DEL 07 PARA EL 09 JULIO.xlsm"
    uv run planeacion-validar --muestra 5 datos/*.xlsm --exportar-csv diferencias.csv

Cada .xlsm de planeación es autosuficiente: en la hoja PEDIDOS trae pegado el
ECOM crudo del día (la entrada) y en la hoja PLANEACION el reparto que hizo Rudy
(el resultado a superar). El comando reprocesa la entrada con el mismo camino que
usa la app y coteja zona por zona.

Dos decisiones que hacen honesta la medición:
- El balanceo corre SIN warm-start. Si partiera de la planeación guardada de ese
  mismo día de semana, estaría comparándose contra sí misma.
- No se filtra por fecha: dos de los archivos cubren dos jornadas que Rudy planeó
  juntas, y sus totales de PLANEACION son la suma de ambas.

Cada archivo pesa ~30 MB y se abre dos veces (bloque de ECOM y hoja PLANEACION),
así que hay que contar cerca de un minuto por día analizado.
"""

import argparse
import csv
import random
import sys
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from pydantic import ValidationError

from planeacion.application.dto.planeacion import PlaneacionCompleta
from planeacion.config.contenedor import crear_contenedor, crear_generar_planeacion
from planeacion.config.settings import Settings
from planeacion.domain.errores import ErrorDeDominio
from planeacion.domain.modelo.balanceo import REGLAS_POR_DEFECTO, ReglasBalanceo
from planeacion.domain.servicios.comparador_asignaciones import (
    ComparacionAsignaciones,
    comparar_asignaciones,
)
from planeacion.domain.servicios.parseo_zonas import normalizar_nombre_zona
from planeacion.infraestructura.adaptadores.salida.excel.lector_ecom import FormatoEcomInvalido
from planeacion.infraestructura.adaptadores.salida.excel.lector_ecom_embebido import LectorEcomEmbebido
from planeacion.infraestructura.adaptadores.salida.excel.lector_referencia import (
    LectorReferenciaExcel,
    TotalesPlaneacion,
)

_SEMILLA_POR_DEFECTO = 20260810

# Tolerancias al cotejar totales: los de PLANEACION salen de fórmulas de Excel en
# coma flotante, así que no son comparables al centavo exacto contra los Decimal
# de la app. Un desfase mayor que esto ya no es ruido binario: es lectura mala.
_TOLERANCIA_PESOS = Decimal("1")
_TOLERANCIA_KILOS = Decimal("0.01")

_ENCABEZADOS_CSV = (
    "archivo",
    "fecha",
    "zona",
    "municipio",
    "carro_manual",
    "carro_propuesto",
    "clientes",
    "pesos",
)


@dataclass(frozen=True)
class ResultadoValidacion:
    """Lo que deja un archivo analizado: para la tabla resumen y para el CSV."""

    archivo: str
    planeacion: PlaneacionCompleta
    comparacion: ComparacionAsignaciones
    totales_manuales: TotalesPlaneacion
    zonas_sin_carro: int
    descuadres: tuple[str, ...]  # vacío = la entrada reconstruida es la que se planeó

    @property
    def cuadra(self) -> bool:
        return not self.descuadres


def _leer_manual(ruta: Path) -> tuple[dict[str, str], TotalesPlaneacion]:
    """De la hoja PLANEACION: el reparto zona→carro y la fila de totales."""
    with LectorReferenciaExcel(ruta) as lector:
        if not lector.tiene_hoja("PLANEACION"):
            raise FormatoEcomInvalido(f"{ruta.name} no tiene hoja PLANEACION: no hay contra qué comparar.")
        manual = {
            normalizar_nombre_zona(fila.zona): fila.carro for fila in lector.leer_asignaciones_planeacion()
        }
        return manual, lector.leer_totales_planeacion()


def _descuadres(planeacion: PlaneacionCompleta, manuales: TotalesPlaneacion) -> list[str]:
    """Diferencias entre lo que leyó la app y la fila "Ventas Totales" del manual.

    Vacío es la condición para que el día valga como medición. Un descuadre no
    siempre significa que el bloque se leyó mal: en al menos un archivo el ECOM
    pegado quedó más grande que lo que se planeó, porque se copió antes de que
    cerrara el día. En cualquiera de los dos casos la propuesta se habría armado
    sobre una entrada distinta a la que tuvo Rudy, así que el día no se promedia.
    """
    problemas = []
    if planeacion.total_facturas != manuales.facturas:
        problemas.append(f"facturas {planeacion.total_facturas} vs {manuales.facturas}")
    if planeacion.total_clientes != manuales.clientes:
        problemas.append(f"clientes {planeacion.total_clientes} vs {manuales.clientes}")
    if abs(planeacion.total_pesos - manuales.pesos) > _TOLERANCIA_PESOS:
        problemas.append(f"pesos {planeacion.total_pesos:,.2f} vs {manuales.pesos:,.2f}")
    if abs(planeacion.total_kilos - manuales.kilos) > _TOLERANCIA_KILOS:
        problemas.append(f"kilos {planeacion.total_kilos:,.2f} vs {manuales.kilos:,.2f}")
    return problemas


def _imprimir_detalle(resultado: ResultadoValidacion) -> None:
    planeacion = resultado.planeacion
    comparacion = resultado.comparacion
    print("=" * 100)
    print(f"{resultado.archivo} — {planeacion.fecha.isoformat()} ({planeacion.dia_semana})")
    print("Balanceo SIN warm-start: reparto desde cero, sin mirar planeaciones guardadas.")
    print("Pivote sin filtro de fecha: se toma el bloque de ECOM completo del archivo.")
    print("-" * 100)

    print(
        f"  Totales app        : {planeacion.total_facturas} facturas | "
        f"{planeacion.total_clientes} clientes | ${planeacion.total_pesos:,.2f} | "
        f"{planeacion.total_kilos:,.2f} kg"
    )
    print(
        f"  Totales PLANEACION : {resultado.totales_manuales.facturas} facturas | "
        f"{resultado.totales_manuales.clientes} clientes | "
        f"${resultado.totales_manuales.pesos:,.2f} | {resultado.totales_manuales.kilos:,.2f} kg"
    )
    if resultado.cuadra:
        print("  -> CUADRAN")
    else:
        print(f"  -> NO CUADRAN: {'; '.join(resultado.descuadres)}")
        print("  El bloque de ECOM pegado no es el que se planeó: este día NO entra al resumen.")
        return

    print(
        f"  Zonas en PLANEACION: {comparacion.zonas_manuales} | comparables: {comparacion.comparables} "
        f"| sin propuesta de la app: {len(comparacion.sin_propuesta)} | "
        f"sin carro elegible: {resultado.zonas_sin_carro}"
    )
    print(
        f"  COINCIDENCIA: {comparacion.coincidencias}/{comparacion.comparables} = "
        f"{comparacion.porcentaje:.1%}   (pesimista sobre las {comparacion.zonas_manuales} "
        f"del manual: {comparacion.porcentaje_pesimista:.1%})"
    )

    if comparacion.diferencias:
        print(f"\n  Diferencias ({len(comparacion.diferencias)}):")
        for diferencia in comparacion.diferencias:
            print(
                f"    {diferencia.zona[:52]:52s} manual {diferencia.carro_manual:>3s} -> "
                f"propuesto {diferencia.carro_propuesto:>3s}  "
                f"({diferencia.clientes} cli, ${diferencia.pesos:,.2f})"
            )
    if comparacion.sin_propuesta:
        print(f"\n  Zonas del manual que la app no asignó ({len(comparacion.sin_propuesta)}):")
        for zona in comparacion.sin_propuesta:
            print(f"    {zona}")


def _imprimir_resumen(resultados: list[ResultadoValidacion]) -> None:
    print("\n" + "=" * 100)
    print("RESUMEN")
    print("=" * 100)
    print(f"{'Archivo':45s} {'Zonas':>6s} {'Coinciden':>10s} {'%':>7s} {'Sin carro':>10s}")
    for resultado in resultados:
        comparacion = resultado.comparacion
        print(
            f"{resultado.archivo[:45]:45s} {comparacion.comparables:6d} "
            f"{comparacion.coincidencias:10d} {comparacion.porcentaje:7.1%} "
            f"{resultado.zonas_sin_carro:10d}"
        )
    porcentajes = [resultado.comparacion.porcentaje for resultado in resultados]
    print("-" * 100)
    print(f"{'PROMEDIO':45s} {'':6s} {'':10s} {sum(porcentajes) / len(porcentajes):7.1%}")
    print(f"{'MINIMO':45s} {'':6s} {'':10s} {min(porcentajes):7.1%}")
    print(f"{'MAXIMO':45s} {'':6s} {'':10s} {max(porcentajes):7.1%}")
    _imprimir_balance(resultados)


def _imprimir_balance(resultados: list[ResultadoValidacion]) -> None:
    """CV promedio por municipio sobre todos los días medidos.

    Va desglosado y no solo en total porque un municipio se puede desbalancear
    sin que el promedio general lo muestre: Chiquinquirá tiene tres carros y
    Tunja muchos más, así que el promedio los diluye.
    """
    clientes: dict[str, list[float]] = {}
    pesos: dict[str, list[float]] = {}
    for resultado in resultados:
        for municipio, metricas in resultado.planeacion.resultado.metricas_finales.items():
            clientes.setdefault(municipio, []).append(metricas.cv_clientes)
            pesos.setdefault(municipio, []).append(metricas.cv_pesos)
    print("\nBALANCE (CV promedio de los dias medidos, mas bajo es mejor)")
    print(f"{'Municipio':45s} {'Dias':>6s} {'CV clientes':>12s} {'CV pesos':>12s}")
    for municipio in sorted(clientes):
        muestras_clientes = clientes[municipio]
        muestras_pesos = pesos[municipio]
        print(
            f"{municipio[:45]:45s} {len(muestras_clientes):6d} "
            f"{sum(muestras_clientes) / len(muestras_clientes):12.1%} "
            f"{sum(muestras_pesos) / len(muestras_pesos):12.1%}"
        )
    todos_clientes = [cv for muestras in clientes.values() for cv in muestras]
    todos_pesos = [cv for muestras in pesos.values() for cv in muestras]
    if todos_clientes:
        print(
            f"{'TODOS':45s} {len(todos_clientes):6d} "
            f"{sum(todos_clientes) / len(todos_clientes):12.1%} "
            f"{sum(todos_pesos) / len(todos_pesos):12.1%}"
        )


def _exportar_csv(resultados: list[ResultadoValidacion], destino: Path) -> int:
    """Vuelca las diferencias de todos los días. Una zona que difiere todos los
    días delata una regla de negocio faltante; una que difiere un solo día es
    apenas otra forma válida de equilibrar."""
    filas = 0
    with destino.open("w", newline="", encoding="utf-8") as archivo:
        escritor = csv.writer(archivo)
        escritor.writerow(_ENCABEZADOS_CSV)
        for resultado in resultados:
            for diferencia in resultado.comparacion.diferencias:
                escritor.writerow(
                    [
                        resultado.archivo,
                        resultado.planeacion.fecha.isoformat(),
                        diferencia.zona,
                        diferencia.municipio,
                        diferencia.carro_manual,
                        diferencia.carro_propuesto,
                        diferencia.clientes,
                        f"{diferencia.pesos:.2f}",
                    ]
                )
                filas += 1
    return filas


def _elegir_archivos(rutas: list[Path], muestra: int | None, semilla: int) -> list[Path]:
    existentes = sorted(ruta for ruta in rutas if ruta.exists())
    if muestra is None or muestra >= len(existentes):
        return existentes
    elegidos = random.Random(semilla).sample(existentes, muestra)
    print(f"Muestra de {muestra} de {len(existentes)} archivos (semilla {semilla}, reproducible).")
    return sorted(elegidos)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compara la planeación automática contra la manual de archivos .xlsm históricos."
    )
    parser.add_argument("rutas", type=Path, nargs="+", help="archivos .xlsm de planeación")
    parser.add_argument(
        "--muestra",
        type=int,
        default=None,
        help="analiza solo N archivos elegidos al azar con una semilla fija",
    )
    parser.add_argument(
        "--semilla",
        type=int,
        default=_SEMILLA_POR_DEFECTO,
        help=f"semilla del muestreo, para poder repetir la corrida (default {_SEMILLA_POR_DEFECTO})",
    )
    parser.add_argument(
        "--exportar-csv", type=Path, default=None, help="vuelca todas las diferencias a un CSV"
    )
    parser.add_argument(
        "--w-frecuencia",
        type=float,
        default=REGLAS_POR_DEFECTO.w_frecuencia,
        help=(
            "peso del desempate por costumbre (default "
            f"{REGLAS_POR_DEFECTO.w_frecuencia}); con 0 se mide el balanceo sin ese termino"
        ),
    )
    args = parser.parse_args()

    archivos = _elegir_archivos(args.rutas, args.muestra, args.semilla)
    if not archivos:
        print("ERROR: ninguno de los archivos indicados existe.", file=sys.stderr)
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

    caso_uso = crear_generar_planeacion(crear_contenedor(settings), lector=LectorEcomEmbebido())
    reglas = ReglasBalanceo(w_frecuencia=args.w_frecuencia)
    print(f"Peso del desempate por frecuencia: {args.w_frecuencia}")
    resultados: list[ResultadoValidacion] = []
    fallidos: list[str] = []
    for ruta in archivos:
        print(f"\nProcesando {ruta.name} (puede tardar ~1 min)...")
        try:
            planeacion = caso_uso.ejecutar(ruta, reglas=reglas, usar_historico=False, todas_las_fechas=True)
            manual, totales = _leer_manual(ruta)
        except (ErrorDeDominio, FormatoEcomInvalido, KeyError) as error:
            sys.stdout.flush()
            print(f"ERROR en {ruta.name}: {error}", file=sys.stderr)
            fallidos.append(ruta.name)
            continue
        resultado = ResultadoValidacion(
            archivo=ruta.name,
            planeacion=planeacion,
            comparacion=comparar_asignaciones(manual, planeacion.asignaciones()),
            totales_manuales=totales,
            zonas_sin_carro=len(planeacion.resultado.zonas_sin_carro),
            descuadres=tuple(_descuadres(planeacion, totales)),
        )
        resultados.append(resultado)
        _imprimir_detalle(resultado)

    medibles = [resultado for resultado in resultados if resultado.cuadra]
    descuadrados = [resultado.archivo for resultado in resultados if not resultado.cuadra]
    if not medibles:
        print("Ningún archivo quedó en condiciones de medirse.", file=sys.stderr)
        return 1

    _imprimir_resumen(medibles)
    if descuadrados:
        print(f"\nDescartados por descuadre de totales ({len(descuadrados)}): {', '.join(descuadrados)}")
    if fallidos:
        print(f"Archivos que fallaron: {', '.join(fallidos)}")
    if args.exportar_csv is not None:
        filas = _exportar_csv(medibles, args.exportar_csv)
        print(f"\n{filas} diferencias exportadas a {args.exportar_csv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
