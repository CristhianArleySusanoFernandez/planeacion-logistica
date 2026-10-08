"""Comando de validación: qué tan cerca queda la propuesta de la planeación manual.

Uso:
    uv run planeacion-validar "datos/DEL 07 PARA EL 09 JULIO.xlsm"
    uv run planeacion-validar --muestra 5 datos/*.xlsm --exportar-csv diferencias.csv
    uv run planeacion-validar datos/*.xlsm --ecom "datos/infpedidos*.xls"

Cada .xlsm de planeación es autosuficiente: en la hoja PEDIDOS trae pegado el
ECOM crudo del día (la entrada) y en la hoja PLANEACION el reparto que hizo Rudy
(el resultado a superar). El comando reprocesa la entrada con el mismo camino que
usa la app y coteja zona por zona.

Con ``--ecom`` la entrada sale de los .xls sueltos de ECOM en vez del bloque
pegado, emparejando cada .xlsm con el .xls de la MISMA fecha de pedidos. Es el
camino más fiel: el .xls es el archivo que la app recibe en producción por el
Paso 1, mientras que el bloque pegado es una copia que puede haberse pegado a
mitad de jornada. Un día sin su .xls no se mide (y se reporta).

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
import re
import statistics
import sys
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from pydantic import ValidationError

from planeacion.application.dto.planeacion import PlaneacionCompleta
from planeacion.config.contenedor import crear_contenedor, crear_generar_planeacion
from planeacion.config.settings import Settings
from planeacion.domain.errores import ErrorDeDominio
from planeacion.domain.modelo import CargaCarro, MetricasDesbalance, ZonaAgregada
from planeacion.domain.modelo.balanceo import REGLAS_POR_DEFECTO, ReglasBalanceo
from planeacion.domain.servicios.balanceador import calcular_metricas
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

# Los .xls de ECOM llevan la fecha de los pedidos en el nombre:
# "infpedidos202610070.27834700.xls" -> 2026-10-07.
_FECHA_EN_NOMBRE = re.compile(r"infpedidos(\d{8})")

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
    manual: dict[str, str]  # zona -> carro, tal como lo repartio la operacion
    comparacion: ComparacionAsignaciones
    totales_manuales: TotalesPlaneacion
    zonas_sin_carro: int
    descuadres: tuple[str, ...]  # vacío = la entrada reconstruida es la que se planeó

    @property
    def cuadra(self) -> bool:
        return not self.descuadres


def emparejar_por_fecha(xlsm: list[Path], ecom: list[Path]) -> tuple[dict[Path, Path], list[Path]]:
    """Cada .xlsm con el .xls de ECOM de su misma fecha de pedidos.

    La fecha del .xls sale de su nombre (``infpedidos20261007....xls``) y la del
    .xlsm de la columna Fecha de su bloque pegado. No se empareja por el nombre del
    .xlsm: esos nombres traen erratas y además nombran el día de ENTREGA, no el de
    los pedidos. Devuelve el emparejamiento y los .xlsm que quedaron sin pareja.
    """
    por_fecha: dict[date, Path] = {}
    for ruta in ecom:
        coincidencia = _FECHA_EN_NOMBRE.search(ruta.name)
        if coincidencia is None:
            print(f"AVISO: no pude sacarle la fecha al nombre de {ruta.name}; se ignora.", file=sys.stderr)
            continue
        por_fecha[datetime.strptime(coincidencia.group(1), "%Y%m%d").date()] = ruta

    parejas: dict[Path, Path] = {}
    sueltos: list[Path] = []
    for ruta in xlsm:
        with LectorReferenciaExcel(ruta) as lector:
            fecha = lector.fecha_de_pedidos()
        pareja = por_fecha.get(fecha) if fecha is not None else None
        if pareja is None:
            sueltos.append(ruta)
        else:
            parejas[ruta] = pareja
    return parejas, sueltos


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
    print(f"{'MEDIANA':45s} {'':6s} {'':10s} {statistics.median(porcentajes):7.1%}")
    print(f"{'MINIMO':45s} {'':6s} {'':10s} {min(porcentajes):7.1%}")
    print(f"{'MAXIMO':45s} {'':6s} {'':10s} {max(porcentajes):7.1%}")
    _imprimir_por_dia(resultados)
    _imprimir_balance(resultados)
    _imprimir_peor_dia(resultados)


def metricas_del_manual(resultado: ResultadoValidacion) -> dict[str, MetricasDesbalance]:
    """CV del reparto que hizo la operación, para poder compararlo con el propuesto.

    Para que la comparación sea justa, lo único que cambia respecto del CV de la
    propuesta es el mapeo zona → carro: mismas zonas, mismo pool por municipio,
    mismos carros (incluidos los que quedaron vacíos, que son los que más
    empujan el CV para arriba) y la misma función ``calcular_metricas``.

    Una zona que la operación puso en un carro de otro pool —pasa: hay zonas de
    Tunja repartidas por la ruta 11, que es de Miraflores— no entra en este
    cálculo, porque contarla mezclaría los pools.
    """
    por_municipio: dict[str, MetricasDesbalance] = {}
    for municipio, cargas in resultado.planeacion.resultado.cargas_por_municipio.items():
        zonas_por_carro: dict[str, list[ZonaAgregada]] = {carga.carro.numero: [] for carga in cargas}
        for carga in cargas:
            for zona in carga.zonas:
                numero = resultado.manual.get(zona.zona.nombre)
                if numero in zonas_por_carro:
                    zonas_por_carro[numero].append(zona)
        por_municipio[municipio] = calcular_metricas(
            municipio,
            [CargaCarro(carro=carga.carro, zonas=zonas_por_carro[carga.carro.numero]) for carga in cargas],
        )
    return por_municipio


def _imprimir_por_dia(resultados: list[ResultadoValidacion]) -> None:
    """Un día por fila: fecha, día de la semana, coincidencia y CV por municipio.

    El promedio esconde la forma de los datos: un día flojo y uno perfecto dan el
    mismo promedio que dos regulares, y no se arreglan igual.
    """
    municipios = sorted(
        {
            municipio
            for resultado in resultados
            for municipio in resultado.planeacion.resultado.metricas_finales
        }
    )
    encabezado = f"{'Fecha':12s} {'Dia':10s} {'Coincide':>9s}"
    for municipio in municipios:
        encabezado += f" {municipio[:11]:>11s}"
    print("\nPOR DIA (el CV por municipio va como clientes/pesos; mas bajo es mejor)")
    print(encabezado)
    for resultado in sorted(resultados, key=lambda r: r.planeacion.fecha):
        fila = (
            f"{resultado.planeacion.fecha.isoformat():12s} "
            f"{resultado.planeacion.dia_semana:10s} "
            f"{resultado.comparacion.porcentaje:9.1%}"
        )
        finales = resultado.planeacion.resultado.metricas_finales
        for municipio in municipios:
            metricas = finales.get(municipio)
            celda = f"{metricas.cv_clientes:.0%}/{metricas.cv_pesos:.0%}" if metricas is not None else "-"
            fila += f" {celda:>11s}"
        print(fila)


def _imprimir_peor_dia(resultados: list[ResultadoValidacion]) -> None:
    """Las diferencias zona por zona del día que peor coincidió.

    Es el día que más tiene para enseñar: si las diferencias se concentran en un
    municipio o en un par de carros, hay una regla que falta; si están repartidas,
    es otra forma válida de equilibrar.
    """
    peor = min(resultados, key=lambda r: r.comparacion.porcentaje)
    comparacion = peor.comparacion
    print("\n" + "=" * 100)
    print(
        f"PEOR DIA: {peor.archivo} — {peor.planeacion.fecha.isoformat()} "
        f"({peor.planeacion.dia_semana}), {comparacion.porcentaje:.1%} "
        f"({comparacion.coincidencias}/{comparacion.comparables})"
    )
    print("=" * 100)
    if not comparacion.diferencias:
        print("  Sin diferencias.")
        return
    print(f"{'Zona':55s} {'Municipio':14s} {'Julian':>7s} {'Propuesto':>10s} {'Clientes':>9s} {'Pesos':>14s}")
    for diferencia in sorted(comparacion.diferencias, key=lambda d: (d.municipio, d.zona)):
        print(
            f"{diferencia.zona[:55]:55s} {diferencia.municipio[:14]:14s} "
            f"{diferencia.carro_manual:>7s} {diferencia.carro_propuesto:>10s} "
            f"{diferencia.clientes:9d} {diferencia.pesos:14,.0f}"
        )
    por_municipio: dict[str, int] = {}
    for diferencia in comparacion.diferencias:
        por_municipio[diferencia.municipio] = por_municipio.get(diferencia.municipio, 0) + 1
    print(
        "  Diferencias por municipio: "
        + ", ".join(f"{municipio}={cuantas}" for municipio, cuantas in sorted(por_municipio.items()))
    )


def _imprimir_balance(resultados: list[ResultadoValidacion]) -> None:
    """CV promedio por municipio sobre todos los días medidos.

    Va desglosado y no solo en total porque un municipio se puede desbalancear
    sin que el promedio general lo muestre: Chiquinquirá tiene tres carros y
    Tunja muchos más, así que el promedio los diluye.
    """
    clientes: dict[str, list[float]] = {}
    pesos: dict[str, list[float]] = {}
    clientes_manual: dict[str, list[float]] = {}
    pesos_manual: dict[str, list[float]] = {}
    for resultado in resultados:
        for municipio, metricas in resultado.planeacion.resultado.metricas_finales.items():
            clientes.setdefault(municipio, []).append(metricas.cv_clientes)
            pesos.setdefault(municipio, []).append(metricas.cv_pesos)
        for municipio, metricas in metricas_del_manual(resultado).items():
            clientes_manual.setdefault(municipio, []).append(metricas.cv_clientes)
            pesos_manual.setdefault(municipio, []).append(metricas.cv_pesos)

    def promedio(muestras: list[float]) -> float:
        return sum(muestras) / len(muestras) if muestras else 0.0

    print("\nBALANCE (CV promedio de los dias medidos, mas bajo es mejor)")
    print("La columna 'real' es el reparto de la operacion con las mismas zonas y la misma formula:")
    print("si los dos CV son parecidos, el desbalance es del dia y no de la app.")
    print(
        f"{'Municipio':30s} {'Dias':>5s} {'CV cli app':>11s} {'CV cli real':>12s} "
        f"{'CV $ app':>10s} {'CV $ real':>11s}"
    )
    for municipio in sorted(clientes):
        print(
            f"{municipio[:30]:30s} {len(clientes[municipio]):5d} "
            f"{promedio(clientes[municipio]):11.1%} {promedio(clientes_manual.get(municipio, [])):12.1%} "
            f"{promedio(pesos[municipio]):10.1%} {promedio(pesos_manual.get(municipio, [])):11.1%}"
        )
    todos_clientes = [cv for muestras in clientes.values() for cv in muestras]
    todos_pesos = [cv for muestras in pesos.values() for cv in muestras]
    todos_cli_manual = [cv for muestras in clientes_manual.values() for cv in muestras]
    todos_pesos_manual = [cv for muestras in pesos_manual.values() for cv in muestras]
    if todos_clientes:
        print(
            f"{'TODOS':30s} {len(todos_clientes):5d} "
            f"{promedio(todos_clientes):11.1%} {promedio(todos_cli_manual):12.1%} "
            f"{promedio(todos_pesos):10.1%} {promedio(todos_pesos_manual):11.1%}"
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


def _expandir(patrones: list[str]) -> list[Path]:
    """Expande globs: PowerShell y cmd no los expanden solos."""
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
    parser.add_argument("rutas", nargs="+", help="archivos .xlsm de planeación (acepta globs)")
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
        "--ecom",
        nargs="+",
        default=None,
        help="los .xls sueltos de ECOM (acepta globs). La entrada del Paso 1 sale de ellos en vez "
        "del bloque pegado en el .xlsm, emparejando por fecha de pedidos. Es el archivo real de "
        "producción; un día sin su .xls no se mide.",
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

    archivos = _elegir_archivos(_expandir(args.rutas), args.muestra, args.semilla)
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

    contenedor = crear_contenedor(settings)
    parejas: dict[Path, Path] = {}
    if args.ecom:
        sueltos_ecom = _expandir(args.ecom)
        parejas, sin_pareja = emparejar_por_fecha(archivos, sueltos_ecom)
        print(
            f"Entrada: los {len(sueltos_ecom)} .xls sueltos de ECOM (el archivo real del Paso 1); "
            f"emparejados {len(parejas)} de {len(archivos)} día(s) por fecha de pedidos."
        )
        if sin_pareja:
            print(
                f"NO se miden {len(sin_pareja)} día(s) por no tener su .xls: "
                + ", ".join(ruta.name for ruta in sin_pareja)
            )
        archivos = [ruta for ruta in archivos if ruta in parejas]
        if not archivos:
            print("ERROR: ningún .xlsm quedó emparejado con un .xls.", file=sys.stderr)
            return 1
        # Lector por defecto: el de los .xlsx/.xls sueltos, el mismo que usa la app.
        caso_uso = crear_generar_planeacion(contenedor)
    else:
        caso_uso = crear_generar_planeacion(contenedor, lector=LectorEcomEmbebido())
    reglas = ReglasBalanceo(w_frecuencia=args.w_frecuencia)
    print(f"Peso del desempate por frecuencia: {args.w_frecuencia}")
    resultados: list[ResultadoValidacion] = []
    fallidos: list[str] = []
    for ruta in archivos:
        print(f"\nProcesando {ruta.name} (puede tardar ~1 min)...")
        try:
            entrada = parejas.get(ruta, ruta)
            planeacion = caso_uso.ejecutar(
                entrada, reglas=reglas, usar_historico=False, todas_las_fechas=True
            )
            manual, totales = _leer_manual(ruta)
        except (ErrorDeDominio, FormatoEcomInvalido, KeyError) as error:
            sys.stdout.flush()
            print(f"ERROR en {ruta.name}: {error}", file=sys.stderr)
            fallidos.append(ruta.name)
            continue
        resultado = ResultadoValidacion(
            archivo=ruta.name,
            planeacion=planeacion,
            manual=manual,
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
