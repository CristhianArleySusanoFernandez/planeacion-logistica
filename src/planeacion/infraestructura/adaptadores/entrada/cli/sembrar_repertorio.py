"""Siembra del repertorio de zonas por carro y día desde las hojas PLANEACION históricas.

Uso:
    uv run planeacion-sembrar-repertorio datos/*.xlsm
    uv run planeacion-sembrar-repertorio "datos/DEL_24_PAR_EL_26_JUNIO.xlsm" ...

De cada .xlsm salen dos cosas: los pares (carro, zona) de la hoja PLANEACION
(col A = carro, col B = zona) y el DÍA al que pertenecen, que se deriva de la
fecha de los pedidos del bloque de ECOM pegado en la hoja PEDIDOS. El día no se
saca del nombre del archivo: los nombres tienen erratas ("DEL_24_PAR_EL_26") y
además nombran el día de ENTREGA, mientras que todo el sistema (el pivote, el
warm-start, `planeaciones.dia_semana`) se maneja con el día de los PEDIDOS.
Sembrar por el día de entrega dejaría el repertorio en una clave que el
balanceador nunca consulta.

Se cuenta cuántas veces se observó cada trío (carro, zona, día): esa frecuencia
va a la columna `frecuencia` y es lo que después deja distinguir una regla
estable de un reemplazo puntual. Se siembra TODO lo observado, sin mínimo: qué
conservar lo decide la usuaria en la interfaz, no este script.

Los archivos que no son de fiar se reportan y quedan fuera en vez de contaminar
el repertorio (ver `motivo_de_descarte`).
"""

import argparse
import statistics
import sys
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from planeacion.application.puertos.salida.repositorios import ParRepertorio
from planeacion.config.contenedor import Contenedor, crear_contenedor
from planeacion.config.settings import Settings
from planeacion.domain.modelo import dia_de
from planeacion.domain.servicios.parseo_zonas import normalizar_nombre_zona
from planeacion.infraestructura.adaptadores.salida.excel.lector_ecom_embebido import LectorEcomEmbebido
from planeacion.infraestructura.adaptadores.salida.excel.lector_referencia import (
    HOJA_PLANEACION,
    LectorReferenciaExcel,
)

# Un archivo con muchas menos zonas que la mediana del lote es trabajo abandonado
# a medias, no una jornada chica: "DEL 08 PARA EL 12 AGOSTO" tiene 2 zonas contra
# las ~70 de un día normal, porque ese día se rehízo en otro archivo.
FRACCION_VOLUMEN_ANOMALO = 0.25


@dataclass(frozen=True)
class LecturaArchivo:
    """Lo que se extrajo de un .xlsm, antes de decidir si se usa."""

    archivo: str
    dias: tuple[str, ...]  # días de la semana de los pedidos del bloque, ordenados
    facturas_bloque: int
    facturas_planeacion: int
    pares: tuple[tuple[str, str], ...]  # (carro, zona) de la hoja PLANEACION

    @property
    def zonas(self) -> int:
        return len({zona for _, zona in self.pares})


def minimo_de_zonas(lecturas: list[LecturaArchivo], fraccion: float = FRACCION_VOLUMEN_ANOMALO) -> int:
    """El piso de zonas por debajo del cual un archivo se considera abandonado.

    Relativo a la MEDIANA del lote y no un número fijo, porque cuántas zonas tiene
    un día normal depende del negocio y cambia con el tiempo; la mediana además no
    se corre por los propios archivos anómalos que se quieren detectar.
    """
    if not lecturas:
        return 0
    return int(statistics.median(lectura.zonas for lectura in lecturas) * fraccion)


def motivo_de_descarte(lectura: LecturaArchivo, minimo_zonas: int) -> str | None:
    """Por qué este archivo no debe sembrar repertorio, o None si sí puede.

    El descuadre de totales es el mismo criterio que usa ``planeacion-validar``:
    si el bloque de ECOM pegado no es el que se planeó, la hoja PLANEACION
    describe el reparto de otra entrada y sus pares no son evidencia de nada.
    """
    if not lectura.pares:
        return "la hoja PLANEACION no trae ningún par (carro, zona)"
    if not lectura.dias:
        return "el bloque de ECOM no trae ninguna fecha legible: no se puede saber de qué día es"
    if len(lectura.dias) > 1:
        # El reparto manual cubre las dos jornadas como un bloque único, así que
        # no hay forma de decir a cuál pertenece cada zona. Atribuirlo a las dos
        # sería inventar evidencia; atribuirlo a una, elegir al azar.
        return (
            f"el bloque cubre {len(lectura.dias)} jornadas ({', '.join(lectura.dias)}) "
            "y la hoja PLANEACION no dice a cuál pertenece cada zona"
        )
    if lectura.facturas_bloque != lectura.facturas_planeacion:
        return (
            f"el bloque de ECOM pegado no es el que se planeó "
            f"({lectura.facturas_bloque} facturas contra {lectura.facturas_planeacion} de PLANEACION)"
        )
    if lectura.zonas < minimo_zonas:
        return f"volumen anómalo: {lectura.zonas} zonas (el piso del lote es {minimo_zonas})"
    return None


def contar_frecuencias(lecturas: list[LecturaArchivo]) -> Counter[tuple[str, str, str]]:
    """Cuántas veces se observó cada (carro, zona, día) en los archivos usables.

    Dentro de un archivo un par cuenta UNA sola vez aunque la hoja lo repita: la
    unidad de observación es la jornada, no la fila.
    """
    frecuencias: Counter[tuple[str, str, str]] = Counter()
    for lectura in lecturas:
        dia = lectura.dias[0]
        frecuencias.update({(carro, zona, dia) for carro, zona in lectura.pares})
    return frecuencias


def cruzar_pares(
    pares: set[tuple[str, str, str]],
    numeros_carros: set[str],
    nombres_zonas: set[str],
) -> tuple[set[tuple[str, str, str]], dict[str, set[str]], set[str]]:
    """Separa los tríos (carro, zona, día) que casan con la base de los desconocidos.

    Los carros desconocidos vuelven con los días en que aparecieron: en agosto
    salen carros de refuerzo sobre todo los sábados, y saber en qué días
    trabajaron es lo que permite decidir si darlos de alta.
    """
    validos = {trio for trio in pares if trio[0] in numeros_carros and trio[1] in nombres_zonas}
    carros_desconocidos: dict[str, set[str]] = {}
    for carro, _, dia in pares:
        if carro not in numeros_carros:
            carros_desconocidos.setdefault(carro, set()).add(dia)
    zonas_desconocidas = {zona for _, zona, _ in pares if zona not in nombres_zonas}
    return validos, carros_desconocidos, zonas_desconocidas


def distribucion_de_frecuencias(frecuencias: Counter[tuple[str, str, str]]) -> dict[str, int]:
    """Cuántos pares se vieron 1 vez, 2 veces y 3 o más.

    El reporte muestra la distribución en vez de filtrar por un mínimo: un par de
    una sola vez es sospechoso, no necesariamente basura, y esa decisión es de la
    usuaria.
    """
    conteo = Counter(min(veces, 3) for veces in frecuencias.values())
    return {"1 vez": conteo[1], "2 veces": conteo[2], "3+ veces": conteo[3]}


def zonas_que_quedarian_huerfanas(frecuencias: Mapping[ParRepertorio, int]) -> list[str]:
    """Zonas que perderían su ÚLTIMO carro si se borra todo lo de frecuencia 0.

    Es el daño colateral de ``--borrar-frecuencia-cero``: una zona cuyos pares son
    todos configuración a mano se queda sin nadie que la reparta, y el balanceador
    va a mandarla a ``zonas_sin_carro`` todos los días. Se avisa antes de borrar
    para que la usuaria pueda configurarlas de nuevo a conciencia.
    """
    con_observaciones = {par.nombre_zona for par, veces in frecuencias.items() if veces > 0}
    todas = {par.nombre_zona for par in frecuencias}
    return sorted(todas - con_observaciones)


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


def _leer_archivo(ruta: Path) -> LecturaArchivo | None:
    """Un .xlsm → su lectura, o None si ni siquiera tiene la hoja PLANEACION."""
    with LectorReferenciaExcel(ruta) as lector:
        if not lector.tiene_hoja(HOJA_PLANEACION):
            print(f"AVISO: {ruta.name} no tiene hoja {HOJA_PLANEACION}; se salta.", file=sys.stderr)
            return None
        pares = {
            (fila.carro, normalizar_nombre_zona(fila.zona)) for fila in lector.leer_asignaciones_planeacion()
        }
        totales = lector.leer_totales_planeacion()

    lineas = LectorEcomEmbebido().leer(ruta)
    fechas = {linea.fecha for linea in lineas if linea.fecha is not None}
    return LecturaArchivo(
        archivo=ruta.name,
        dias=tuple(sorted({dia_de(fecha) for fecha in fechas})),
        facturas_bloque=len({linea.pedido for linea in lineas}),
        facturas_planeacion=totales.facturas,
        pares=tuple(sorted(pares)),
    )


def _imprimir_descartes(descartes: list[tuple[str, str]]) -> None:
    if not descartes:
        return
    print(f"\nArchivos DESCARTADOS ({len(descartes)}): no siembran repertorio.")
    for archivo, motivo in descartes:
        print(f"  - {archivo}: {motivo}")


def _reportar(contenedor: Contenedor, sembrados: int) -> None:
    print("\nRepertorio resultante por carro (pares carro-zona-día):")
    matriz = contenedor.carro_zonas.obtener_matriz()
    por_carro: Counter[str] = Counter()
    for dias in matriz.values():
        for numero, zonas in dias.items():
            por_carro[numero] += len(zonas)
    for carro in sorted(contenedor.carros.listar(), key=lambda c: (len(c.numero), c.numero)):
        total = por_carro.get(carro.numero, 0)
        marca = "" if total else "  <- sin configurar"
        conductor = carro.conductor or "sin conductor"
        print(f"  carro {carro.numero:>2} ({conductor}): {total} pares{marca}")

    con_carro = {zona for dias in matriz.values() for zonas in dias.values() for zona in zonas}
    activas = [zona.nombre for zona in contenedor.zonas.listar() if zona.activa]
    sin_carro = [nombre for nombre in activas if nombre not in con_carro]
    print(
        f"\nZonas activas sin ningún carro en ningún día: {len(sin_carro)} de {len(activas)} "
        "(configurables en la UI: Configuración > Zonas por carro)."
    )

    # Los que quedan en 0 no salieron de este histórico: son configuración puesta
    # a mano o restos del backfill de la migración 003, que replicó a los seis
    # días lo que había sin día. Distinguirlos importa porque no tienen ninguna
    # evidencia detrás, y en la matriz se ven igual que los observados.
    en_cero = [par for par, veces in contenedor.carro_zonas.frecuencias().items() if veces == 0]
    print(
        f"\nPares con frecuencia 0 (NO salieron de este histórico): {len(en_cero)} "
        f"contra {sembrados} sembrados con frecuencia >= 1."
    )
    if en_cero:
        por_dia = Counter(par.dia_semana for par in en_cero)
        print("  por día: " + ", ".join(f"{dia}={n}" for dia, n in sorted(por_dia.items())))
        print("  Son configuración manual o restos del backfill de la migración 003.")
        print("  Para borrarlos, re-correr con --borrar-frecuencia-cero.")


def _borrar_frecuencia_cero(contenedor: Contenedor) -> None:
    """Borra lo que no tiene evidencia, avisando antes qué zonas quedan huérfanas."""
    frecuencias = contenedor.carro_zonas.frecuencias()
    huerfanas = zonas_que_quedarian_huerfanas(frecuencias)
    if huerfanas:
        print(f"\nAVISO: {len(huerfanas)} zona(s) se quedan SIN NINGÚN carro al borrar:")
        for nombre in huerfanas:
            print(f"  - {nombre}")
        print("  El balanceador las va a reportar en zonas_sin_carro hasta reconfigurarlas.")
    borrados = contenedor.carro_zonas.quitar_sin_observaciones()
    print(f"\nBorrados {borrados} par(es) con frecuencia 0. Queda solo lo observado en el histórico.")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Siembra la tabla carro_zonas desde las hojas PLANEACION de .xlsm históricos."
    )
    parser.add_argument("rutas", nargs="+", help="rutas (o globs) de los .xlsm de planeación")
    parser.add_argument(
        "--borrar-frecuencia-cero",
        action="store_true",
        help="después de sembrar, borra los pares que quedaron en frecuencia 0 (los que no "
        "salieron de ningún histórico: configuración a mano o restos del backfill de la "
        "migración 003). DESTRUCTIVO: avisa qué zonas quedan sin ningún carro antes de borrar.",
    )
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

    print(f"Leyendo {len(rutas)} archivo(s) (hoja {HOJA_PLANEACION} + bloque de ECOM de PEDIDOS)...")
    lecturas = []
    for ruta in rutas:
        lectura = _leer_archivo(ruta)
        if lectura is None:
            continue
        dias = "+".join(lectura.dias) or "sin fecha"
        print(f"  {lectura.archivo}: {len(lectura.pares)} pares, {lectura.zonas} zonas, {dias}")
        lecturas.append(lectura)

    if not lecturas:
        print("ERROR: no se pudo leer ningún archivo.", file=sys.stderr)
        return 1

    minimo = minimo_de_zonas(lecturas)
    descartes: list[tuple[str, str]] = []
    usables: list[LecturaArchivo] = []
    for lectura in lecturas:
        motivo = motivo_de_descarte(lectura, minimo)
        if motivo:
            descartes.append((lectura.archivo, motivo))
        else:
            usables.append(lectura)
    _imprimir_descartes(descartes)

    if not usables:
        print("ERROR: todos los archivos quedaron descartados.", file=sys.stderr)
        return 1
    print(f"\nArchivos usables: {len(usables)} de {len(lecturas)}.")

    frecuencias = contar_frecuencias(usables)
    contenedor = crear_contenedor(settings)
    numeros_carros = {carro.numero for carro in contenedor.carros.listar()}
    nombres_zonas = {zona.nombre for zona in contenedor.zonas.listar()}
    validos, carros_desconocidos, zonas_desconocidas = cruzar_pares(
        set(frecuencias), numeros_carros, nombres_zonas
    )

    print(f"\nTríos (carro, zona, día) distintos en el histórico: {len(frecuencias)}")
    print("Distribución por veces observado:")
    for etiqueta, cuantos in distribucion_de_frecuencias(frecuencias).items():
        print(f"  visto {etiqueta}: {cuantos} par(es)")
    if carros_desconocidos:
        print("\nAVISO: carros del histórico que NO están en la base (se saltan):")
        for numero in sorted(carros_desconocidos, key=lambda n: (len(n), n)):
            dias_del_carro = ", ".join(sorted(carros_desconocidos[numero]))
            print(f"  - carro {numero}: aparece en {dias_del_carro}")
        print("  Si son refuerzos reales, darlos de alta en Configuración > Carros y re-sembrar.")
    if zonas_desconocidas:
        print("\nAVISO: zonas del histórico que NO casan con zonas.nombre (se saltan):")
        for zona in sorted(zonas_desconocidas):
            print(f"  - {zona}")

    por_sembrar = {
        ParRepertorio(carro, zona, dia, frecuencias[(carro, zona, dia)]) for carro, zona, dia in validos
    }
    contenedor.carro_zonas.asignar_lote(sorted(por_sembrar))
    print(f"\nPares sembrados: {len(por_sembrar)} (cada uno con su frecuencia observada).")

    _reportar(contenedor, len(por_sembrar))
    if args.borrar_frecuencia_cero:
        _borrar_frecuencia_cero(contenedor)
    return 0


if __name__ == "__main__":
    sys.exit(main())
