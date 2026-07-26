"""Comando de fusión de zonas duplicadas por normalización de nombre.

Uso:
    uv run planeacion-fusionar-zonas              # simula: muestra el plan, no toca nada
    uv run planeacion-fusionar-zonas --aplicar    # fusiona de verdad

Toma los grupos que detecta ``planeacion-auditar-zonas``, elige como canónica la
variante con más clientes (empate: la más corta, luego alfabética) y reapunta a
ella los clientes, el repertorio, los overrides y el histórico de planeaciones
de las demás, borrándolas después. Es una red de seguridad: si la auditoría no
encuentra duplicados, no hay nada que hacer.
"""

import argparse
import sys
from collections import defaultdict

from pydantic import ValidationError

from planeacion.config.contenedor import Contenedor, crear_contenedor
from planeacion.config.settings import Settings
from planeacion.domain.servicios.auditoria_zonas import (
    GrupoDuplicado,
    ReferenciasMovidas,
    agrupar_duplicados,
    planear_fusion,
)


def _clientes_por_zona(contenedor: Contenedor) -> dict[str, int]:
    conteo: dict[str, int] = defaultdict(int)
    for cliente in contenedor.clientes.listar():
        if cliente.zona is not None:
            conteo[cliente.zona.nombre] += 1
    return conteo


def _imprimir_plan(grupos: list[GrupoDuplicado]) -> None:
    print(f"\nGrupos de zonas duplicadas: {len(grupos)}")
    for grupo in grupos:
        plan = planear_fusion(grupo)
        clientes = {v.nombre: v.clientes for v in grupo.variantes}
        print(f"\n  clave normalizada: {grupo.clave_normalizada!r}")
        print(f"    CANÓNICA (sobrevive): {plan.canonica!r}  ({clientes[plan.canonica]} clientes)")
        for variante in plan.variantes:
            print(f"    se absorbe:           {variante!r}  ({clientes[variante]} clientes)")


def _aplicar(contenedor: Contenedor, grupos: list[GrupoDuplicado]) -> tuple[int, ReferenciasMovidas]:
    zonas_fusionadas = 0
    total = ReferenciasMovidas()
    for grupo in grupos:
        plan = planear_fusion(grupo)
        for variante in plan.variantes:
            movidas = contenedor.zonas.fusionar_zona(variante, plan.canonica)
            zonas_fusionadas += 1
            total += movidas
            print(
                f"  {variante!r} -> {plan.canonica!r}: "
                f"{movidas.clientes} cliente(s), {movidas.repertorio} par(es) de repertorio, "
                f"{movidas.overrides} override(s), {movidas.planeaciones} asignación(es)"
            )
    return zonas_fusionadas, total


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fusiona zonas duplicadas que normalizan al mismo nombre."
    )
    parser.add_argument(
        "--aplicar",
        action="store_true",
        help="ejecuta la fusión; sin esta bandera solo simula (no escribe nada)",
    )
    args = parser.parse_args()

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
    zonas = contenedor.zonas.listar()
    conteo = _clientes_por_zona(contenedor)
    grupos = agrupar_duplicados(zonas, conteo)

    print(f"Zonas en la base: {len(zonas)}")
    if not grupos:
        print("No hay duplicados: nada que fusionar.")
        return 0

    _imprimir_plan(grupos)

    if not args.aplicar:
        print("\n--simular (por defecto): no se escribió nada. Usa --aplicar para fusionar.")
        return 0

    print("\nAplicando la fusión...")
    zonas_fusionadas, total = _aplicar(contenedor, grupos)
    print(
        f"\nListo: {zonas_fusionadas} zona(s) fusionada(s), {total.total} referencia(s) movida(s) "
        f"({total.clientes} clientes, {total.repertorio} repertorio, "
        f"{total.overrides} overrides, {total.planeaciones} planeaciones)."
    )
    print("Corre 'uv run planeacion-auditar-zonas' para confirmar que quedó limpio.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
