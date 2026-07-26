"""Comando de balanceo: reparte las zonas del día entre los carros de cada municipio.

Uso:
    uv run planeacion-balancear datos/pedidos24-26Junio.xlsx
    uv run planeacion-balancear datos/pedidos24-26Junio.xlsx --fecha 2026-06-24 \
        --w-clientes 0.7 --w-pesos 0.3 --interactivo

Imprime el reparto con semáforos de desbalance (CV < 10% verde, 10-20% amarillo,
> 20% rojo) mostrando el CV inicial → final. Con --interactivo Rudy puede mover
zonas entre carros y ver el recálculo en vivo. Nada se guarda sin confirmación.
"""

import argparse
import sys
from datetime import date
from pathlib import Path

from pydantic import ValidationError

from planeacion.application.casos_uso.ajustar_asignacion import CasoDeUsoAjustarAsignacion
from planeacion.application.dto.planeacion import PlaneacionCompleta
from planeacion.application.puertos.entrada.generar_planeacion import GenerarPlaneacion
from planeacion.config.contenedor import crear_contenedor, crear_generar_planeacion
from planeacion.config.settings import Settings
from planeacion.domain.errores import ErrorDeDominio, MovimientoInvalido
from planeacion.domain.modelo import CargaCarro, MetricasDesbalance, ReglasBalanceo
from planeacion.infraestructura.adaptadores.salida.excel.lector_ecom import FormatoEcomInvalido

_MAX_RESULTADOS_BUSQUEDA = 15


def _semaforo(cv: float) -> str:
    if cv < 0.10:
        return "VERDE"
    if cv <= 0.20:
        return "AMARILLO"
    return "ROJO"


def _linea_metricas(iniciales: MetricasDesbalance, finales: MetricasDesbalance) -> str:
    return (
        f"  Desbalance: CV clientes {iniciales.cv_clientes:.1%} -> {finales.cv_clientes:.1%} "
        f"[{_semaforo(finales.cv_clientes)}]  |  CV pesos {iniciales.cv_pesos:.1%} -> "
        f"{finales.cv_pesos:.1%} [{_semaforo(finales.cv_pesos)}]"
    )


def _imprimir_carga(carga: CargaCarro) -> None:
    conductor = f" ({carga.carro.conductor})" if carga.carro.conductor else ""
    print(
        f"  carro {carga.carro.numero}{conductor}: {len(carga.zonas)} zonas | "
        f"{carga.clientes} clientes | ${carga.pesos:,.2f} | {carga.kilos:,.2f} kg"
    )
    for zona in sorted(carga.zonas, key=lambda z: z.zona.nombre):
        fijada = "  [FIJA]" if zona.zona.regla_chiquinquira is not None else ""
        print(f"      - {zona.zona.nombre}  ({zona.clientes} cli, ${zona.pesos:,.2f}){fijada}")


def _imprimir_planeacion(planeacion: PlaneacionCompleta) -> None:
    resultado = planeacion.resultado
    print("=" * 100)
    print(f"PLANEACION — {planeacion.fecha.isoformat()} ({planeacion.dia_semana})")
    if resultado.desde_historico:
        de_fecha = f" del {planeacion.fecha_previa.isoformat()}" if planeacion.fecha_previa else ""
        print(f"Partió de la planeación previa{de_fecha} ({planeacion.dia_semana}, warm-start).")
    else:
        print(f"Sin histórico para '{planeacion.dia_semana}': reparto inicial round-robin por peso.")
    print("=" * 100)

    for municipio, cargas in sorted(resultado.cargas_por_municipio.items()):
        zonas_totales = sum(len(carga.zonas) for carga in cargas)
        print(f"\n[{municipio}]  {len(cargas)} carros, {zonas_totales} zonas")
        for carga in cargas:
            _imprimir_carga(carga)
        print(_linea_metricas(resultado.metricas_iniciales[municipio], resultado.metricas_finales[municipio]))

    if resultado.zonas_sin_carro:
        print(f"\nAVISO: {len(resultado.zonas_sin_carro)} zonas sin ningún carro elegible (sin asignar):")
        for zona in sorted(resultado.zonas_sin_carro, key=lambda z: z.zona.nombre):
            print(f"  - {zona.zona.nombre}  ({zona.clientes} cli, ${zona.pesos:,.2f})")
        print("  Configura su repertorio en la UI (Configuración > Zonas por carro) o con "
              "planeacion-sembrar-repertorio.")

    print("\n" + "-" * 100)
    print(
        f"TOTAL: {planeacion.total_facturas} facturas | {planeacion.total_clientes} clientes | "
        f"${planeacion.total_pesos:,.2f} | {planeacion.total_kilos:,.2f} kg"
    )
    if planeacion.no_resueltos:
        print(f"Clientes sin zona (no entran al balanceo): {len(planeacion.no_resueltos)} "
              "-> usar planeacion-resolver-nuevos")
    if planeacion.pedidos_excluidos_por_fecha:
        print(f"Pedidos excluidos por fecha: {planeacion.pedidos_excluidos_por_fecha}")


def _elegir_de_lista(opciones: list[str]) -> str | None:
    for numero, opcion in enumerate(opciones, 1):
        print(f"    {numero}. {opcion}")
    respuesta = input("  Número (Enter para volver): ").strip()
    if respuesta.isdigit() and 1 <= int(respuesta) <= len(opciones):
        return opciones[int(respuesta) - 1]
    return None


def _buscar_zona(planeacion: PlaneacionCompleta, texto: str) -> str | None:
    nombres = [
        zona.zona.nombre
        for cargas in planeacion.resultado.cargas_por_municipio.values()
        for carga in cargas
        for zona in carga.zonas
    ]
    clave = " ".join(texto.upper().split())
    coincidencias = sorted(nombre for nombre in nombres if clave in nombre.upper())
    if not coincidencias:
        print(f"  Ninguna zona de la planeación contiene {texto!r}.")
        return None
    if len(coincidencias) == 1:
        return coincidencias[0]
    if len(coincidencias) > _MAX_RESULTADOS_BUSQUEDA:
        print(f"  {len(coincidencias)} zonas coinciden; muestro las primeras {_MAX_RESULTADOS_BUSQUEDA}.")
        coincidencias = coincidencias[:_MAX_RESULTADOS_BUSQUEDA]
    return _elegir_de_lista(coincidencias)


def _municipio_de_zona(planeacion: PlaneacionCompleta, nombre_zona: str) -> str | None:
    for municipio, cargas in planeacion.resultado.cargas_por_municipio.items():
        for carga in cargas:
            if any(zona.zona.nombre == nombre_zona for zona in carga.zonas):
                return municipio
    return None


def _modo_interactivo(planeacion: PlaneacionCompleta) -> None:
    ajustar = CasoDeUsoAjustarAsignacion()
    print("\nMODO INTERACTIVO: mueve zonas entre carros del mismo municipio (Enter para terminar).")
    while True:
        try:
            texto = input("\nMover zona (texto a buscar) > ").strip()
        except (KeyboardInterrupt, EOFError):
            print()
            return
        if not texto:
            return
        nombre_zona = _buscar_zona(planeacion, texto)
        if nombre_zona is None:
            continue
        municipio = _municipio_de_zona(planeacion, nombre_zona)
        if municipio is None:
            continue
        cargas = planeacion.resultado.cargas_por_municipio[municipio]
        print(f"  Zona: {nombre_zona}  [{municipio}]. Carros del municipio:")
        for carga in cargas:
            print(f"    carro {carga.carro.numero}: {carga.clientes} clientes, ${carga.pesos:,.2f}")
        numero_carro = input("  Carro destino > ").strip()
        if not numero_carro:
            continue
        try:
            ajustar.ejecutar(planeacion.resultado, nombre_zona, numero_carro)
        except MovimientoInvalido as error:
            print(f"  X {error}")
            continue
        metricas = planeacion.resultado.metricas_finales[municipio]
        print(
            f"  OK Movida. Nuevo desbalance {municipio}: "
            f"CV clientes {metricas.cv_clientes:.1%} [{_semaforo(metricas.cv_clientes)}], "
            f"CV pesos {metricas.cv_pesos:.1%} [{_semaforo(metricas.cv_pesos)}]"
        )


def _preguntar_guardar(caso_uso: GenerarPlaneacion, planeacion: PlaneacionCompleta) -> None:
    try:
        respuesta = input("\n¿Guardar esta planeación en Supabase? [s/N] ").strip().upper()
    except (KeyboardInterrupt, EOFError):
        respuesta = ""
    if respuesta == "S":
        id_planeacion = caso_uso.guardar(planeacion)
        print(f"Planeación guardada (id {id_planeacion}). La próxima corrida de un "
              f"{planeacion.dia_semana} partirá de ella (warm-start).")
    else:
        print("No se guardó nada.")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Balancea las zonas del día entre los carros de cada municipio."
    )
    parser.add_argument("ruta_ecom", type=Path, help="ruta del .xlsx crudo de ECOM (hoja Hoja1)")
    parser.add_argument("--fecha", type=date.fromisoformat, default=None,
                        help="fecha a planear (AAAA-MM-DD); sin ella, la más frecuente del archivo")
    parser.add_argument("--w-clientes", type=float, default=0.5,
                        help="peso del balance por clientes en la función de costo (default 0.5)")
    parser.add_argument("--w-pesos", type=float, default=0.5,
                        help="peso del balance por plata en la función de costo (default 0.5)")
    parser.add_argument("--interactivo", action="store_true",
                        help="permite mover zonas entre carros con recálculo en vivo")
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

    caso_uso = crear_generar_planeacion(crear_contenedor(settings))
    reglas = ReglasBalanceo(w_clientes=args.w_clientes, w_pesos=args.w_pesos)
    print(f"Leyendo {args.ruta_ecom}, pivoteando y balanceando...")
    try:
        planeacion = caso_uso.ejecutar(args.ruta_ecom, fecha=args.fecha, reglas=reglas)
    except (ErrorDeDominio, FormatoEcomInvalido) as error:
        sys.stdout.flush()
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    _imprimir_planeacion(planeacion)

    if args.interactivo:
        _modo_interactivo(planeacion)
        _imprimir_planeacion(planeacion)

    _preguntar_guardar(caso_uso, planeacion)
    return 0


if __name__ == "__main__":
    sys.exit(main())
