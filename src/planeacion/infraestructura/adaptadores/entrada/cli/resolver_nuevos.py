"""Comando interactivo: sugiere zona a los clientes no resueltos del ECOM del día.

Uso:
    uv run planeacion-resolver-nuevos datos/pedidos24-26Junio.xlsx [--fecha 2026-06-24]

Corre el pivote, toma los clientes sin zona (#N/D o en maestra sin RUTA)
y por cada uno muestra la sugerencia del voto de vecinos para que Rudy decida:
aceptar, elegir una alternativa, asignar manualmente u omitir. Solo lo confirmado
se persiste en Supabase.
"""

import argparse
import sys
from datetime import date
from pathlib import Path

from pydantic import ValidationError

from planeacion.application.dto.clientes_nuevos import ClientePendiente
from planeacion.application.puertos.entrada.resolver_clientes_nuevos import ResolverClientesNuevos
from planeacion.config.contenedor import (
    crear_contenedor,
    crear_generar_pivote,
    crear_resolver_clientes_nuevos,
)
from planeacion.config.settings import Settings
from planeacion.domain.errores import ErrorDeDominio
from planeacion.domain.servicios.normalizacion_ubicacion import normalizar_ubicacion
from planeacion.infraestructura.adaptadores.salida.excel.lector_ecom import FormatoEcomInvalido

_MAX_RESULTADOS_BUSQUEDA = 15
_MOTIVOS = {
    "NO_ESTA_EN_MAESTRA": "no está en la maestra (#N/D)",
    "EN_MAESTRA_SIN_ZONA": "está en la maestra pero sin zona",
}


def _mostrar_ficha(indice: int, total: int, pendiente: ClientePendiente) -> None:
    print("\n" + "-" * 78)
    print(f"[{indice}/{total}] Cliente: {pendiente.codigo} - {pendiente.nombre or '(sin nombre)'}")
    print(f"  Ciudad: {pendiente.ciudad or '?'}  |  Barrio: {pendiente.barrio or '?'}")
    if pendiente.direccion:
        print(f"  Dirección: {pendiente.direccion}")
    print(f"  Motivo: {_MOTIVOS.get(pendiente.motivo, pendiente.motivo)}")
    if pendiente.sugerencia is None:
        print("  Sugerencia: (ninguna: no hay vecinos con esa ciudad/barrio)")
        return
    sugerencia = pendiente.sugerencia
    print(
        f"  Sugerencia: {sugerencia.zona}  "
        f"({sugerencia.vecinos_en_zona} de {sugerencia.total_vecinos} vecinos)  "
        f"[confianza: {sugerencia.confianza}]"
    )
    if sugerencia.alternativas:
        alternativas = "  ·  ".join(f"{zona} ({votos})" for zona, votos in sugerencia.alternativas)
        print(f"  Alternativas: {alternativas}")


def _elegir_de_lista(opciones: list[str]) -> str | None:
    """Muestra opciones numeradas y devuelve la elegida (Enter o valor inválido → None)."""
    for numero, opcion in enumerate(opciones, 1):
        print(f"    {numero}. {opcion}")
    respuesta = input("  Número (Enter para volver): ").strip()
    if respuesta.isdigit() and 1 <= int(respuesta) <= len(opciones):
        return opciones[int(respuesta) - 1]
    return None


def _buscar_zona_manual(nombres_zonas: list[str]) -> str | None:
    texto = input("  Texto a buscar en el nombre de la zona: ").strip()
    if not texto:
        return None
    clave = normalizar_ubicacion(texto)
    coincidencias = [nombre for nombre in nombres_zonas if clave in normalizar_ubicacion(nombre)]
    if not coincidencias:
        print(f"  No hay zonas que contengan {texto!r}.")
        return None
    if len(coincidencias) > _MAX_RESULTADOS_BUSQUEDA:
        print(f"  {len(coincidencias)} zonas coinciden; muestro las primeras {_MAX_RESULTADOS_BUSQUEDA}.")
        coincidencias = coincidencias[:_MAX_RESULTADOS_BUSQUEDA]
    return _elegir_de_lista(coincidencias)


def _preguntar_zona(pendiente: ClientePendiente, nombres_zonas: list[str]) -> str | None:
    """Devuelve la zona elegida para el cliente, o None si Rudy lo omite."""
    hay_sugerencia = pendiente.sugerencia is not None
    hay_alternativas = pendiente.sugerencia is not None and bool(pendiente.sugerencia.alternativas)
    opciones: list[str] = []
    if hay_sugerencia:
        opciones.append("[S] Aceptar sugerencia")
    if hay_alternativas:
        opciones.append("[A] Elegir alternativa")
    opciones.extend(["[M] Asignar manualmente", "[O] Omitir"])

    while True:
        respuesta = input("  " + "  |  ".join(opciones) + " > ").strip().upper()
        if respuesta == "S" and pendiente.sugerencia is not None:
            return pendiente.sugerencia.zona
        if respuesta == "A" and hay_alternativas and pendiente.sugerencia is not None:
            elegida = _elegir_de_lista([zona for zona, _ in pendiente.sugerencia.alternativas])
            if elegida is not None:
                return elegida
        elif respuesta == "M":
            elegida = _buscar_zona_manual(nombres_zonas)
            if elegida is not None:
                return elegida
        elif respuesta == "O":
            return None


def _resolver_interactivo(
    pendientes: list[ClientePendiente],
    resolutor: ResolverClientesNuevos,
    nombres_zonas: list[str],
) -> tuple[int, int, int]:
    resueltos = omitidos = sin_sugerencia = 0
    try:
        for indice, pendiente in enumerate(pendientes, 1):
            _mostrar_ficha(indice, len(pendientes), pendiente)
            if pendiente.sugerencia is None:
                sin_sugerencia += 1
            zona_elegida = _preguntar_zona(pendiente, nombres_zonas)
            if zona_elegida is None:
                omitidos += 1
                continue
            try:
                resolutor.confirmar_cliente(pendiente, zona_elegida)
            except ErrorDeDominio as error:
                print(f"  ERROR: {error} (el cliente queda como omitido)")
                omitidos += 1
                continue
            print(f"  OK: {pendiente.codigo} -> {zona_elegida}")
            resueltos += 1
    except (KeyboardInterrupt, EOFError):
        faltantes = len(pendientes) - resueltos - omitidos
        print(f"\nInterrumpido: quedan {faltantes} clientes sin revisar.")
    return resueltos, omitidos, sin_sugerencia


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Asistente interactivo para asignar zona a los clientes no resueltos del ECOM."
    )
    parser.add_argument("ruta_ecom", type=Path, help="ruta del .xlsx crudo de ECOM (hoja Hoja1)")
    parser.add_argument(
        "--fecha",
        type=date.fromisoformat,
        default=None,
        help="fecha a pivotear (AAAA-MM-DD); sin ella se usa la más frecuente del archivo",
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

    contenedor = crear_contenedor(settings)
    print(f"Leyendo {args.ruta_ecom} y buscando clientes sin zona...")
    try:
        pivote = crear_generar_pivote(contenedor).ejecutar(args.ruta_ecom, fecha=args.fecha)
    except (ErrorDeDominio, FormatoEcomInvalido) as error:
        sys.stdout.flush()
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    if not pivote.no_resueltos:
        print(f"Pivote del {pivote.fecha.isoformat()}: 0 clientes pendientes. Nada que resolver.")
        return 0

    resolutor = crear_resolver_clientes_nuevos(contenedor)
    pendientes = resolutor.pendientes(pivote.no_resueltos)
    nombres_zonas = [zona.nombre for zona in contenedor.zonas.listar()]
    print(f"Pivote del {pivote.fecha.isoformat()}: {len(pendientes)} clientes sin zona por revisar.")

    resueltos, omitidos, sin_sugerencia = _resolver_interactivo(pendientes, resolutor, nombres_zonas)

    print("\n" + "=" * 78)
    print("RESUMEN")
    print("=" * 78)
    print(f"  resueltos (persistidos en Supabase): {resueltos}")
    print(f"  omitidos: {omitidos}")
    print(f"  llegaron sin sugerencia (asignación manual): {sin_sugerencia}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
