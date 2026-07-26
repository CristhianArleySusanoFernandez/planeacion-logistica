"""Comando de solo lectura: detecta zonas duplicadas por normalización de nombre.

Uso:
    uv run planeacion-auditar-zonas

Agrupa las zonas de la tabla ``zonas`` por su nombre normalizado
(``normalizar_nombre_zona``) y reporta los grupos con más de una variante
real, con cuántos clientes tiene asociados cada una. No modifica nada: es el
paso previo a revisar el criterio de zona canónica antes de fusionar.
"""

import sys
from collections import defaultdict

from pydantic import ValidationError

from planeacion.config.contenedor import crear_contenedor
from planeacion.config.settings import Settings
from planeacion.domain.servicios.auditoria_zonas import agrupar_duplicados


def main() -> int:
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
    clientes = contenedor.clientes.listar()

    conteo_por_zona: dict[str, int] = defaultdict(int)
    for cliente in clientes:
        if cliente.zona is not None:
            conteo_por_zona[cliente.zona.nombre] += 1

    grupos = agrupar_duplicados(zonas, conteo_por_zona)

    print(f"Zonas en la base: {len(zonas)}")
    print(f"Clientes con zona: {sum(conteo_por_zona.values())}")

    if not grupos:
        print("\nNo hay duplicados: la normalización de nombre ya alcanza.")
        return 0

    print(f"\nGrupos de zonas duplicadas: {len(grupos)}")
    for grupo in grupos:
        print(f"\n  clave normalizada: {grupo.clave_normalizada!r}")
        for variante in grupo.variantes:
            print(f"    - {variante.nombre!r}  ({variante.clientes} clientes)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
