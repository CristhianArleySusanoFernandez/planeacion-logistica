"""Comando de resincronización de la configuración desde un archivo de corte.

Uso:
    uv run planeacion-resincronizar "datos/DEL 06-10 PARA EL 08-10.xlsm"
    uv run planeacion-resincronizar "datos/..." --aplicar

Por defecto **no toca nada**: compara el archivo con la base y escribe el reporte
en consola y en ``salidas/resincronizacion_<fecha>.md``. Con ``--aplicar`` escribe
y después vuelve a calcular el reporte para confirmar que no quedaron diferencias.

Qué sincroniza y desde dónde: la flota del bloque 2 de ``BASE``, las zonas de la
columna RUTA de ``MAESTRA``, los clientes de ``MAESTRA`` + ``MAESTRA COMPLETA``
(que es la única que trae documento y razón social), las correcciones de
``CAMBIOS`` y los overrides de ``martha ojo``.

Nada se borra: lo que está en la base y no en el archivo se lista en el reporte
para decidirlo a mano. La única excepción son las rutas fuera de 1-22, que quedan
inactivas (no borradas) porque los refuerzos puntuales no son flota.
"""

import argparse
import csv
import sys
from collections import Counter, defaultdict
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from planeacion.config.contenedor import Contenedor, crear_cliente_supabase, crear_contenedor
from planeacion.config.settings import Settings
from planeacion.domain.modelo import (
    Carro,
    CorreccionUbicacion,
    Municipio,
    OverrideZona,
    Zona,
    clave_conductor,
)
from planeacion.domain.servicios.auditoria_zonas import agrupar_duplicados, planear_fusion
from planeacion.domain.servicios.parseo_zonas import (
    detectar_regla_chiquinquira,
    normalizar_nombre_zona,
    parsear_municipio,
)
from planeacion.infraestructura.adaptadores.entrada.cli.resincronizacion import (
    RUTA_MAXIMA,
    RUTA_MINIMA,
    Cambio,
    DatosCompletos,
    FilaCliente,
    OrigenDeZona,
    PlanClientes,
    PlanCorrecciones,
    Planes,
    PlanFlota,
    PlanOverrides,
    PlanZonas,
    mapear_origenes,
    planear_clientes,
    planear_correcciones,
    planear_flota,
    planear_overrides,
    planear_zonas,
    reparar_mojibake,
    tiene_mojibake,
    zonas_a_desactivar,
)
from planeacion.infraestructura.adaptadores.salida.excel.lector_referencia import (
    HOJA_MAESTRA_COMPLETA,
    FilaMaestra,
    FilaRutaBase,
    LectorReferenciaExcel,
)
from planeacion.infraestructura.adaptadores.salida.supabase._filas import como_filas

_MUNICIPIOS_PROPIOS = ("BARBOSA", "CHIQUINQUIRA", "TUNJA")
_MAX_EJEMPLOS = 25


def _municipio_de_pool(ciudad: str | None) -> Municipio:
    """La CIUDAD del bloque 2 → el pool con el que la ruta se balancea.

    Las cabeceras que no son municipio propio (MUZO, FLORIAN, GARAGOA,
    MIRAFLORES, VILLA DELEYVA) caen todas en OTROS; su nombre real se conserva
    aparte en ``municipio_real``.
    """
    texto = (ciudad or "").upper()
    for nombre in _MUNICIPIOS_PROPIOS:
        if nombre in texto:
            return Municipio(nombre=nombre)
    return Municipio(nombre="OTROS")


def _es_ruta_de_flota(fila: FilaRutaBase) -> bool:
    try:
        numero = int(fila.numero)
    except ValueError:
        return False
    return RUTA_MINIMA <= numero <= RUTA_MAXIMA and fila.conductor is not None


def flota_del_archivo(rutas: list[FilaRutaBase]) -> list[Carro]:
    """Las rutas 1-22 con conductor como flota activa.

    ``es_externo`` y ``costo_diario`` van en falso y cero en todas: en la
    operación de octubre de 2026 no hay carro externo (la 16 es CARLOS 1, propia).
    """
    carros = []
    for fila in rutas:
        if not _es_ruta_de_flota(fila):
            continue
        zona_principal = normalizar_nombre_zona(fila.zona_principal or "")
        lado = (
            detectar_regla_chiquinquira(zona_principal, parsear_municipio(zona_principal))
            if zona_principal
            else None
        )
        conductor = fila.conductor
        carros.append(
            Carro(
                numero=fila.numero,
                conductor=conductor,
                auxiliar=fila.auxiliar,
                municipio=_municipio_de_pool(fila.ciudad),
                es_externo=False,
                activo=True,
                conductor_clave=clave_conductor(conductor),
                municipio_real=fila.ciudad,
                lado_chiquinquira=lado,
            )
        )
    return carros


class _Reporte:
    """Acumula las líneas del reporte para imprimirlas y guardarlas en el .md."""

    def __init__(self) -> None:
        self._lineas: list[str] = []

    def titulo(self, texto: str) -> None:
        self._lineas.append(f"\n## {texto}\n")

    def linea(self, texto: str = "") -> None:
        self._lineas.append(texto)

    def lista(self, cambios: list[Cambio], etiqueta: str) -> None:
        """Los cambios, recortados: 9.000 clientes no caben en una consola."""
        if not cambios:
            return
        self.linea(f"- {etiqueta}: **{len(cambios)}**")
        for cambio in cambios[:_MAX_EJEMPLOS]:
            self.linea(f"    - {cambio}")
        if len(cambios) > _MAX_EJEMPLOS:
            self.linea(f"    - ... y {len(cambios) - _MAX_EJEMPLOS} más")

    def texto(self) -> str:
        return "\n".join(self._lineas)

    def imprimir(self) -> None:
        print(self.texto())


def _reportar_flota(reporte: _Reporte, plan: PlanFlota) -> None:
    reporte.titulo("Flota (bloque 2 de BASE)")
    reporte.linea(f"- rutas sin cambios: {plan.sin_cambios}")
    reporte.linea(f"- rutas nuevas: {len(plan.nuevas)}")
    reporte.linea(f"- rutas actualizadas: {len(plan.actualizadas)}")
    reporte.linea(f"- rutas desactivadas (están en la base y no en el archivo): {len(plan.desactivadas)}")
    reporte.lista(plan.cambios, "cambios")
    reporte.lista(
        plan.erratas_en_base,
        "erratas en BASE (dejarían dos rutas activas con el mismo conductor): NO se aplican",
    )


def _reportar_zonas(reporte: _Reporte, plan: PlanZonas, fusiones: list[tuple[str, str]]) -> None:
    reporte.titulo("Zonas (columna RUTA de MAESTRA)")
    reporte.linea(f"- zonas nuevas a crear: **{len(plan.nuevas)}**")
    for zona in plan.nuevas[:_MAX_EJEMPLOS]:
        reporte.linea(f"    - {zona.nombre!r} → municipio {zona.municipio.nombre}")
    if len(plan.nuevas) > _MAX_EJEMPLOS:
        reporte.linea(f"    - ... y {len(plan.nuevas) - _MAX_EJEMPLOS} más")

    reporte.linea(
        f"- zonas que están en la base y ya no en la maestra: **{len(plan.solo_en_base)}** "
        "(NO se borran ni se desactivan; se listan con sus clientes para decidir)"
    )
    for nombre, clientes in plan.solo_en_base[:_MAX_EJEMPLOS]:
        reporte.linea(f"    - {nombre!r} — {clientes} cliente(s)")
    if len(plan.solo_en_base) > _MAX_EJEMPLOS:
        reporte.linea(f"    - ... y {len(plan.solo_en_base) - _MAX_EJEMPLOS} más")

    if plan.nombres_malformados:
        reporte.linea("- nombres con paréntesis sin cerrar (la normalización no los arregla):")
        for nombre in plan.nombres_malformados:
            reporte.linea(f"    - {nombre!r}")
    reporte.linea(f"- variantes a fusionar por espacios: **{len(fusiones)}**")
    for variante, canonica in fusiones:
        reporte.linea(f"    - {variante!r} → {canonica!r}")


def _reportar_zonas_vacias(reporte: _Reporte, a_desactivar: list[Zona], aplicar: bool) -> None:
    """Las zonas que se quedan sin clientes con la maestra nueva.

    Se listan SIEMPRE, se escriben solo con --desactivar-vacias: apagar una zona
    cambia lo que la app ofrece en pantalla y es una decisión, no un efecto
    secundario de resincronizar. Nunca se borran, así que su repertorio —que es
    trabajo de configuración— sobrevive y la zona puede volver.
    """
    reporte.titulo(f"Zonas que se quedan sin clientes ({len(a_desactivar)})")
    destino = "se **desactivan**" if aplicar else "NO se tocan (pasar --desactivar-vacias)"
    reporte.linea(f"Con la maestra nueva no les queda ningún cliente. {destino}; nunca se borran.")
    for zona in a_desactivar[:_MAX_EJEMPLOS]:
        reporte.linea(f"- `{zona.nombre}` ({zona.municipio.nombre})")
    if len(a_desactivar) > _MAX_EJEMPLOS:
        reporte.linea(f"- ... y {len(a_desactivar) - _MAX_EJEMPLOS} más")


def _reportar_origenes(reporte: _Reporte, origenes: list[OrigenDeZona]) -> None:
    """De dónde vienen los clientes de cada zona nueva.

    Es la entrada de la herencia de repertorio: una zona que es el 100 % de una
    vieja puede heredar su repertorio tal cual, y una que mezcla dos lo hereda
    ponderado. Solo se muestran las zonas que mezclan o cambiaron de nombre; las
    que siguen igual no tienen nada que contar.
    """
    por_zona: dict[str, list[OrigenDeZona]] = {}
    for origen in origenes:
        por_zona.setdefault(origen.zona_nueva, []).append(origen)
    mezcladas = {
        zona: lista
        for zona, lista in por_zona.items()
        if len(lista) > 1 or (lista and lista[0].zona_vieja != zona)
    }
    reporte.titulo(f"De dónde viene cada zona nueva ({len(mezcladas)} de {len(por_zona)})")
    reporte.linea(
        "Fracción de los clientes de la zona nueva que venían de cada zona vieja. Es lo que usa "
        "`planeacion-heredar-repertorio` para estimar el repertorio de la zona nueva."
    )
    for zona, lista in sorted(mezcladas.items(), key=lambda par: -sum(o.clientes for o in par[1]))[
        :_MAX_EJEMPLOS
    ]:
        total = lista[0].total_de_la_zona
        detalle = ", ".join(f"{o.zona_vieja} {o.fraccion:.0%}" for o in lista[:4])
        reporte.linea(f"- `{zona}` ({total} cliente(s)): {detalle}")
    if len(mezcladas) > _MAX_EJEMPLOS:
        reporte.linea(f"- ... y {len(mezcladas) - _MAX_EJEMPLOS} más (están todas en el CSV)")


def _reportar_clientes(reporte: _Reporte, plan: PlanClientes) -> None:
    reporte.titulo("Clientes (MAESTRA + MAESTRA COMPLETA)")
    reporte.linea(f"- sin cambios: {plan.sin_cambios}")
    reporte.linea(f"- nuevos: **{len(plan.nuevos)}**")
    reporte.linea(f"- actualizados: **{len(plan.actualizados)}**")
    reporte.linea(f"- duplicados en el archivo con la misma zona (se toma una): {plan.duplicados_en_archivo}")
    reporte.lista(
        plan.duplicados_con_zonas_distintas,
        "duplicados con zonas DISTINTAS: NO se aplican, lo decide una persona",
    )
    reporte.linea(
        f"- clientes de la base que no están en la maestra nueva: **{len(plan.solo_en_base)}** (NO se borran)"
    )
    for codigo in plan.solo_en_base[:_MAX_EJEMPLOS]:
        reporte.linea(f"    - {codigo}")
    if len(plan.solo_en_base) > _MAX_EJEMPLOS:
        reporte.linea(f"    - ... y {len(plan.solo_en_base) - _MAX_EJEMPLOS} más")
    reporte.lista(plan.cambios_de_zona, "cambios de zona")
    reporte.lista(plan.cambios_de_ubicacion, "cambios de ciudad/barrio/dirección")
    reporte.lista(
        plan.direcciones_sospechosas,
        "direcciones sospechosas (la columna trae la ciudad): se conserva la de la base",
    )
    reporte.lista(plan.rellenados, "documento/razón social rellenados (solo si estaban vacíos)")
    reporte.lista(plan.zonas_no_encontradas, "filas cuya RUTA no casa con ninguna zona")


def _reportar_correcciones(reporte: _Reporte, plan: PlanCorrecciones) -> None:
    reporte.titulo("Correcciones de ubicación (CAMBIOS)")
    reporte.linea(f"- sin cambios: {plan.sin_cambios}")
    reporte.linea(f"- nuevas: {len(plan.nuevas)} · actualizadas: {len(plan.actualizadas)}")
    reporte.linea(f"- en la base y no en el archivo: {len(plan.solo_en_base)} (NO se borran)")
    reporte.lista(plan.cambios, "cambios")


def _reportar_overrides(reporte: _Reporte, plan: PlanOverrides) -> None:
    reporte.titulo("Overrides de zona (martha ojo)")
    reporte.linea(f"- sin cambios: {plan.sin_cambios}")
    reporte.linea(f"- nuevos: {len(plan.nuevos)} · actualizados: {len(plan.actualizados)}")
    reporte.linea(f"- en la base y no en el archivo: {len(plan.solo_en_base)} (NO se borran)")
    reporte.lista(plan.cambios, "cambios")
    reporte.lista(plan.zonas_no_encontradas, "overrides descartados porque su zona no existe")


def _filas_de(maestra: Sequence[FilaMaestra]) -> list[FilaCliente]:
    """Las filas de la hoja MAESTRA sin el tipo del lector de Excel."""
    return [
        FilaCliente(
            codigo=fila.codigo,
            direccion=fila.direccion,
            ciudad=fila.ciudad,
            barrio=fila.barrio,
            ruta=fila.ruta,
        )
        for fila in maestra
    ]


def _construir_planes(lector: LectorReferenciaExcel, contenedor: Contenedor) -> Planes:
    """Lee el archivo, lee la base y cruza las cinco entidades."""
    rutas = list(lector.leer_rutas())
    maestra = list(lector.leer_maestra())
    completa: dict[str, DatosCompletos] = {}
    if lector.tiene_hoja(HOJA_MAESTRA_COMPLETA):
        # Los nombres de esta hoja vienen doblemente codificados (`PEÃ‘A`); se
        # reparan al leerlos y lo que no se pueda reparar se cuenta para el reporte.
        completa = {
            fila.codigo: DatosCompletos(
                documento=reparar_mojibake(fila.documento),
                razon_social=reparar_mojibake(fila.razon_social),
            )
            for fila in lector.leer_maestra_completa()
        }
    cambios_hoja = list(lector.leer_cambios())
    overrides_hoja = list(lector.leer_overrides())

    carros_base = contenedor.carros.listar()
    zonas_base = contenedor.zonas.listar()
    clientes_base = contenedor.clientes.listar()

    clientes_por_zona: dict[str, int] = defaultdict(int)
    for cliente in clientes_base:
        if cliente.zona is not None:
            clientes_por_zona[cliente.zona.nombre] += 1

    plan_flota = planear_flota(flota_del_archivo(rutas), carros_base)
    plan_zonas = planear_zonas((fila.ruta for fila in maestra if fila.ruta), zonas_base, clientes_por_zona)

    # Las zonas nuevas todavía no están en la base, pero los clientes que las usan
    # sí se pueden planear: el cruce es por nombre y el guardado las crea antes.
    zonas_por_nombre: dict[str, Zona] = {zona.nombre: zona for zona in zonas_base}
    zonas_por_nombre.update({zona.nombre: zona for zona in plan_zonas.nuevas})

    plan_clientes = planear_clientes(_filas_de(maestra), completa, clientes_base, zonas_por_nombre)
    plan_correcciones = planear_correcciones(
        [
            CorreccionUbicacion(
                cliente_codigo=fila.codigo,
                ciudad_real=fila.ciudad_real,
                barrio_real=fila.barrio_real,
            )
            for fila in cambios_hoja
        ],
        contenedor.correcciones.listar(),
    )
    plan_overrides = planear_overrides(
        [OverrideZona(cliente_codigo=fila.codigo, zona_nombre=fila.zona) for fila in overrides_hoja],
        contenedor.overrides.listar(),
        zonas_por_nombre,
    )

    origenes = mapear_origenes(_filas_de(maestra), clientes_base, zonas_por_nombre)
    # Los clientes que la zona tendrá DESPUÉS de aplicar. Se cuenta sobre el mapeo
    # de orígenes, que recorre TODAS las filas de la maestra: contar solo el plan
    # dejaría afuera a los clientes que no cambiaron —la mayoría— y haría pasar
    # por vacía a cualquier zona cuya gente se quedó quieta.
    clientes_finales: Counter[str] = Counter()
    for origen in origenes:
        clientes_finales[origen.zona_nueva] = origen.total_de_la_zona
    # Los que están en la base y no en la maestra no se borran, así que siguen
    # sosteniendo a su zona.
    zona_de_base = {cliente.codigo: cliente.zona for cliente in clientes_base}
    for codigo in plan_clientes.solo_en_base:
        zona = zona_de_base.get(codigo)
        if zona is not None:
            clientes_finales[zona.nombre] += 1
    a_desactivar = zonas_a_desactivar(zonas_base, clientes_finales)

    fusiones = [
        (variante, planear_fusion(grupo).canonica)
        for grupo in agrupar_duplicados(zonas_base, clientes_por_zona)
        for variante in planear_fusion(grupo).variantes
    ]
    sin_reparar = sum(
        1
        for datos in completa.values()
        if tiene_mojibake(datos.razon_social) or tiene_mojibake(datos.documento)
    )
    return Planes(
        flota=plan_flota,
        zonas=plan_zonas,
        clientes=plan_clientes,
        correcciones=plan_correcciones,
        overrides=plan_overrides,
        fusiones=fusiones,
        razones_sociales_mal_codificadas=sin_reparar,
        origenes=origenes,
        a_desactivar=a_desactivar,
    )


# Las cinco tablas que la resincronización puede tocar. Se respaldan enteras
# antes de escribir: aunque nada se borre, 7.600 clientes actualizados de una vez
# no se deshacen a mano, y un CSV por tabla es lo único que permite volver atrás.
TABLAS_A_RESPALDAR = ("carros", "zonas", "clientes", "correcciones_ubicacion", "overrides_zona")

_TAMANO_PAGINA = 1000  # el límite por defecto de PostgREST


def respaldar(destino: Path, tablas: Sequence[str] = TABLAS_A_RESPALDAR) -> dict[str, int]:
    """Vuelca cada tabla completa a ``destino/<tabla>.csv``. Devuelve filas por tabla.

    Va contra el cliente de Supabase y no contra los repositorios a propósito: un
    respaldo tiene que traer las columnas **como están en la base**, incluidos los
    ids y lo que el dominio no modela, porque es lo que haría falta para restaurar.
    """
    cliente = crear_cliente_supabase(Settings())
    destino.mkdir(parents=True, exist_ok=True)
    conteos: dict[str, int] = {}
    for tabla in tablas:
        filas: list[dict[str, Any]] = []
        inicio = 0
        while True:
            respuesta = cliente.table(tabla).select("*").range(inicio, inicio + _TAMANO_PAGINA - 1).execute()
            pagina = como_filas(respuesta.data or [])
            filas.extend(pagina)
            if len(pagina) < _TAMANO_PAGINA:
                break
            inicio += _TAMANO_PAGINA
        ruta = destino / f"{tabla}.csv"
        columnas = sorted({clave for fila in filas for clave in fila})
        with ruta.open("w", encoding="utf-8", newline="") as archivo:
            escritor = csv.DictWriter(archivo, fieldnames=columnas)
            escritor.writeheader()
            escritor.writerows(filas)
        conteos[tabla] = len(filas)
        print(f"  {tabla}: {len(filas)} fila(s) → {ruta}")
    return conteos


def _escribir_reporte(reporte: _Reporte, ruta_salida: Path) -> None:
    ruta_salida.parent.mkdir(parents=True, exist_ok=True)
    ruta_salida.write_text(reporte.texto(), encoding="utf-8")
    print(f"\nReporte guardado en {ruta_salida}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Resincroniza la configuración de Supabase desde un .xlsm de corte."
    )
    parser.add_argument("ruta_xlsm", type=Path, help="el .xlsm más reciente (el archivo de corte)")
    parser.add_argument(
        "--aplicar",
        action="store_true",
        help="escribe los cambios en Supabase (por defecto solo reporta)",
    )
    parser.add_argument(
        "--desactivar-vacias",
        action="store_true",
        help="las zonas que queden sin ningún cliente pasan a activo = false (nunca se borran y "
        "conservan su repertorio). Se listan igual sin esta bandera.",
    )
    parser.add_argument(
        "--solo-respaldo",
        action="store_true",
        help="exporta las tablas a salidas/respaldo_<fecha>/ y termina (para revisarlo antes de aplicar)",
    )
    parser.add_argument(
        "--salidas",
        type=Path,
        default=Path("salidas"),
        help="carpeta donde queda el reporte .md (por defecto: salidas/)",
    )
    args = parser.parse_args()

    if not args.ruta_xlsm.exists():
        print(f"No existe el archivo {args.ruta_xlsm}", file=sys.stderr)
        return 1
    try:
        contenedor = crear_contenedor(Settings())
    except ValidationError as error:
        print(f"Faltan credenciales de Supabase: {error}", file=sys.stderr)
        return 1

    if args.solo_respaldo:
        print("RESPALDO (las tablas enteras, sin tocar nada)")
        respaldar(args.salidas / f"respaldo_{date.today().isoformat()}")
        return 0

    with LectorReferenciaExcel(args.ruta_xlsm) as lector:
        faltantes = lector.hojas_faltantes()
        if faltantes:
            print(f"Al archivo le faltan hojas: {', '.join(faltantes)}", file=sys.stderr)
            return 1
        planes = _construir_planes(lector, contenedor)
        reporte = _armar_reporte(
            args.ruta_xlsm, planes, aplicado=False, desactivar_vacias=args.desactivar_vacias
        )
        reporte.imprimir()
        _escribir_reporte(reporte, args.salidas / f"resincronizacion_{date.today().isoformat()}.md")
        # El mapeo sale SIEMPRE, incluso en modo reporte: es la entrada de la
        # herencia de repertorio y conviene poder revisarlo antes de aplicar nada.
        _escribir_mapeo(planes.origenes, args.salidas / f"mapeo_zonas_{date.today().isoformat()}.csv")

        if not args.aplicar:
            print("\nModo reporte: no se escribió nada. Para aplicar: --aplicar")
            return 0

        _aplicar(contenedor, planes, desactivar_vacias=args.desactivar_vacias)
        print("\n" + "=" * 78)
        print("VERIFICACION (se recalcula el reporte contra la base ya escrita)")
        print("=" * 78)
        verificacion = _armar_reporte(
            args.ruta_xlsm,
            _construir_planes(lector, contenedor),
            aplicado=True,
            desactivar_vacias=args.desactivar_vacias,
        )
        verificacion.imprimir()
        _escribir_reporte(
            verificacion, args.salidas / f"resincronizacion_{date.today().isoformat()}_verificacion.md"
        )
    return 0


def _armar_reporte(ruta: Path, planes: Planes, aplicado: bool, desactivar_vacias: bool = False) -> _Reporte:
    reporte = _Reporte()
    reporte.linea(f"# Resincronización {'(verificación)' if aplicado else '(reporte)'} — {date.today()}")
    reporte.linea()
    reporte.linea(f"Archivo de corte: `{ruta.name}`")
    reporte.linea()
    reporte.linea(
        "Criterio: lo que está en el archivo manda; lo que solo está en la base **no se borra**, "
        "se lista para decidirlo a mano."
    )
    _reportar_flota(reporte, planes.flota)
    _reportar_zonas(reporte, planes.zonas, planes.fusiones)
    _reportar_zonas_vacias(reporte, planes.a_desactivar, aplicar=desactivar_vacias)
    _reportar_origenes(reporte, planes.origenes)
    _reportar_clientes(reporte, planes.clientes)
    _reportar_correcciones(reporte, planes.correcciones)
    _reportar_overrides(reporte, planes.overrides)
    reporte.titulo("Codificación de los nombres")
    reporte.linea(
        "- MAESTRA COMPLETA trae los nombres doblemente codificados (`PEÃ‘A` en vez de `PEÑA`); "
        "se reparan al leer la hoja, probando cp1252 y latin-1 carácter por carácter."
    )
    sin_reparar = planes.razones_sociales_mal_codificadas
    if sin_reparar:
        reporte.linea(
            f"- **quedan {sin_reparar} sin reparar** (siguen con `Ã`): revisarlas a mano, "
            "no se inventa nada sobre ellas."
        )
    else:
        reporte.linea("- **no queda ninguna sin reparar.**")
    return reporte


def _escribir_mapeo(origenes: list[OrigenDeZona], destino: Path) -> int:
    """El mapeo zona vieja → zona nueva con sus conteos, para la herencia."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    with destino.open("w", encoding="utf-8", newline="") as archivo:
        escritor = csv.writer(archivo)
        escritor.writerow(["zona_nueva", "zona_vieja", "clientes", "total_de_la_zona", "fraccion"])
        for origen in origenes:
            escritor.writerow(
                [
                    origen.zona_nueva,
                    origen.zona_vieja,
                    origen.clientes,
                    origen.total_de_la_zona,
                    f"{origen.fraccion:.4f}",
                ]
            )
    print(f"Mapeo de zonas guardado en {destino} ({len(origenes)} fila(s))")
    return len(origenes)


def _aplicar(contenedor: Contenedor, planes: Planes, desactivar_vacias: bool = False) -> None:
    plan_flota, plan_zonas = planes.flota, planes.zonas
    plan_clientes, plan_correcciones, plan_overrides = planes.clientes, planes.correcciones, planes.overrides
    print("\n" + "=" * 78)
    print("APLICANDO EN SUPABASE")
    print("=" * 78)

    municipios = {carro.municipio.nombre for carro in plan_flota.a_guardar if carro.municipio}
    municipios.update(zona.municipio.nombre for zona in plan_zonas.nuevas)
    municipios.add("OTROS")
    ids_municipios = contenedor.municipios.guardar_lote([Municipio(nombre=n) for n in sorted(municipios)])
    print(f"  municipios: {len(ids_municipios)}")

    if plan_zonas.nuevas:
        contenedor.zonas.guardar_lote(plan_zonas.nuevas, ids_municipios)
    print(f"  zonas nuevas: {len(plan_zonas.nuevas)}")

    for variante, canonica in planes.fusiones:
        movidas = contenedor.zonas.fusionar_zona(variante, canonica)
        print(f"  fusión {variante!r} -> {canonica!r}: {movidas.total} referencia(s)")

    if plan_flota.a_guardar:
        contenedor.carros.guardar_lote(plan_flota.a_guardar, ids_municipios)
    print(f"  rutas escritas: {len(plan_flota.a_guardar)}")

    # Los ids de zona se piden después de crear las nuevas y de fusionar: los
    # clientes y los overrides se guardan con la llave foránea ya resuelta.
    ids_zonas = contenedor.zonas.guardar_lote(contenedor.zonas.listar(), ids_municipios)
    if plan_clientes.a_guardar:
        contenedor.clientes.guardar_lote(plan_clientes.a_guardar, ids_zonas)
    print(f"  clientes escritos: {len(plan_clientes.a_guardar)}")

    if plan_correcciones.a_guardar:
        contenedor.correcciones.guardar_lote(plan_correcciones.a_guardar)
    print(f"  correcciones escritas: {len(plan_correcciones.a_guardar)}")

    if plan_overrides.a_guardar:
        contenedor.overrides.guardar_lote(plan_overrides.a_guardar, ids_zonas)
    print(f"  overrides escritos: {len(plan_overrides.a_guardar)}")

    if desactivar_vacias:
        for zona in planes.a_desactivar:
            contenedor.zonas.actualizar_zona(zona)
        print(f"  zonas desactivadas por quedar sin clientes: {len(planes.a_desactivar)}")
    elif planes.a_desactivar:
        print(
            f"  {len(planes.a_desactivar)} zona(s) quedaron sin clientes y NO se tocaron "
            "(pasar --desactivar-vacias)"
        )
