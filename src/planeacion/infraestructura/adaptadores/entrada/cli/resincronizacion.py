"""Lógica pura de la resincronización: comparar el archivo de corte con la base.

Separada del comando a propósito: acá no hay Supabase ni openpyxl, solo objetos
de dominio entrando y un plan de cambios saliendo, para poder probar el reporte
con dobles en vez de contra la base real.

El criterio es siempre el mismo y vale para las cinco entidades: **lo que está en
el archivo manda, y lo que solo está en la base no se borra**. Una zona o un
cliente que desaparecieron de la maestra pueden ser un error de la maestra de hoy
o un retiro real, y eso no lo decide un script.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum

from planeacion.domain.modelo import (
    Carro,
    Cliente,
    CorreccionUbicacion,
    Municipio,
    OverrideZona,
    Zona,
)
from planeacion.domain.servicios.parseo_zonas import crear_zona, normalizar_nombre_zona

# Las rutas de reparto de la operación de octubre de 2026. Una ruta fuera de este
# rango (las 23+ de los refuerzos puntuales) no se da de alta ni se actualiza: si
# ya existe en la base queda inactiva, y nunca se borra.
RUTA_MINIMA = 1
RUTA_MAXIMA = 22


@dataclass(frozen=True)
class Cambio:
    """Un campo que cambia, para la línea ``antes → después`` del reporte."""

    clave: str
    campo: str
    antes: str | None
    despues: str | None

    def __str__(self) -> str:
        return f"{self.clave}: {self.campo}  {self.antes!r} -> {self.despues!r}"


# La hoja MAESTRA COMPLETA trae los nombres doblemente codificados: los bytes
# UTF-8 se leyeron como si fueran de una tabla de un solo byte, así que 'Ñ' (C3 91)
# quedó como 'Ã‘'. Se deshace volviendo a bytes con la MISMA tabla y decodificando
# como UTF-8. Hay que probar dos tablas: cp1252 arregla la mayoría, pero no sabe
# representar el rango C1 (0x81, 0x8d...), que sí está en latin-1; de ahí los dos
# pasos y no uno.
_TABLAS_DE_REPARACION = ("cp1252", "latin-1")
_MARCA_DE_MOJIBAKE = "Ã"


def _a_bytes_originales(texto: str) -> bytes | None:
    """Deshace la decodificación byte a byte, probando las dos tablas por carácter.

    Por carácter y no por cadena porque hay nombres que mezclan los dos rangos:
    ``'PHA LOGÃSTICA Y DISTRIBUCIÃ“N SAS'`` necesita latin-1 para el ````
    y cp1252 para el ``“``, así que ninguna de las dos sola alcanza.
    """
    crudo = bytearray()
    for caracter in texto:
        for tabla in _TABLAS_DE_REPARACION:
            try:
                crudo += caracter.encode(tabla)
                break
            except UnicodeEncodeError:
                continue
        else:
            return None
    return bytes(crudo)


def reparar_mojibake(texto: str | None) -> str | None:
    """``'PEÃ‘A'`` → ``'PEÑA'``. Lo que no se pueda reparar se devuelve intacto.

    Nunca lanza y nunca inventa: si la doble codificación no se deshace, el texto
    vuelve como vino y queda contado en el reporte. Un nombre de cliente mal
    escrito es mejor que uno corrompido en silencio.
    """
    if texto is None or _MARCA_DE_MOJIBAKE not in texto:
        return texto
    crudo = _a_bytes_originales(texto)
    if crudo is None:
        return texto
    try:
        return crudo.decode("utf-8")
    except UnicodeDecodeError:
        return texto


def tiene_mojibake(texto: str | None) -> bool:
    """Si después de reparar sigue habiendo rastros, hay que mirarlo a mano."""
    return texto is not None and _MARCA_DE_MOJIBAKE in texto


def _texto(valor: object) -> str | None:
    if valor is None:
        return None
    if isinstance(valor, Municipio):
        return valor.nombre
    if isinstance(valor, Zona):
        return valor.nombre
    if isinstance(valor, Decimal):
        # Normalizado, para que 0.0 de la base y 0 del archivo no cuenten como
        # un cambio: la columna es numeric y vuelve con la escala que tenga.
        return format(valor.normalize(), "f")
    if isinstance(valor, Enum):
        return str(valor.value)
    return str(valor)


def _comparar(clave: str, campos: Mapping[str, tuple[object, object]]) -> list[Cambio]:
    """Los campos cuyo valor del archivo difiere del de la base."""
    cambios = []
    for campo, (antes, despues) in campos.items():
        texto_antes, texto_despues = _texto(antes), _texto(despues)
        if texto_antes != texto_despues:
            cambios.append(Cambio(clave=clave, campo=campo, antes=texto_antes, despues=texto_despues))
    return cambios


@dataclass
class Planes:
    """Los cinco planes de una corrida, más lo que se detectó de paso.

    Van juntos porque el reporte y la escritura necesitan los cinco y el orden
    importa: las zonas nuevas se crean antes que los clientes que las usan.
    """

    flota: "PlanFlota"
    zonas: "PlanZonas"
    clientes: "PlanClientes"
    correcciones: "PlanCorrecciones"
    overrides: "PlanOverrides"
    fusiones: list[tuple[str, str]] = field(default_factory=list)
    razones_sociales_mal_codificadas: int = 0


# --------------------------------------------------------------------- flota


@dataclass
class PlanFlota:
    nuevas: list[Carro] = field(default_factory=list)
    actualizadas: list[Carro] = field(default_factory=list)
    desactivadas: list[Carro] = field(default_factory=list)
    cambios: list[Cambio] = field(default_factory=list)
    sin_cambios: int = 0

    @property
    def a_guardar(self) -> list[Carro]:
        return self.nuevas + self.actualizadas + self.desactivadas


def planear_flota(flota_archivo: Sequence[Carro], flota_base: Sequence[Carro]) -> PlanFlota:
    """Las rutas 1-22 se actualizan en sitio; el resto de la base se desactiva.

    "En sitio" es lo importante: el ``numero`` es la identidad y no cambia, así que
    las planeaciones guardadas siguen apuntando a la misma fila aunque el conductor
    y el municipio de esa ruta hoy sean otros.
    """
    plan = PlanFlota()
    por_numero = {carro.numero: carro for carro in flota_base}

    for carro in flota_archivo:
        actual = por_numero.get(carro.numero)
        if actual is None:
            plan.nuevas.append(carro)
            plan.cambios.append(Cambio(carro.numero, "ruta nueva", None, _texto(carro.conductor)))
            continue
        cambios = _comparar(
            carro.numero,
            {
                "conductor": (actual.conductor, carro.conductor),
                "conductor_clave": (actual.conductor_clave, carro.conductor_clave),
                "auxiliar": (actual.auxiliar, carro.auxiliar),
                "municipio": (actual.municipio, carro.municipio),
                "municipio_real": (actual.municipio_real, carro.municipio_real),
                "lado_chiquinquira": (actual.lado_chiquinquira, carro.lado_chiquinquira),
                "es_externo": (actual.es_externo, carro.es_externo),
                "costo_diario": (actual.costo_diario, carro.costo_diario),
                "activo": (actual.activo, carro.activo),
            },
        )
        if cambios:
            plan.cambios.extend(cambios)
            # Se conserva la placa de la base: el bloque 2 no la trae y el bloque 1
            # está desactualizado, así que el archivo no tiene con qué pisarla.
            plan.actualizadas.append(
                Carro(
                    numero=carro.numero,
                    conductor=carro.conductor,
                    placa=actual.placa,
                    auxiliar=carro.auxiliar,
                    municipio=carro.municipio,
                    es_externo=carro.es_externo,
                    costo_diario=carro.costo_diario,
                    activo=carro.activo,
                    conductor_clave=carro.conductor_clave,
                    municipio_real=carro.municipio_real,
                    lado_chiquinquira=carro.lado_chiquinquira,
                )
            )
        else:
            plan.sin_cambios += 1

    numeros_archivo = {carro.numero for carro in flota_archivo}
    for carro in flota_base:
        if carro.numero in numeros_archivo or not carro.activo:
            continue
        plan.desactivadas.append(
            Carro(
                numero=carro.numero,
                conductor=carro.conductor,
                placa=carro.placa,
                auxiliar=carro.auxiliar,
                municipio=carro.municipio,
                es_externo=carro.es_externo,
                costo_diario=carro.costo_diario,
                activo=False,
                conductor_clave=carro.conductor_clave,
                municipio_real=carro.municipio_real,
                lado_chiquinquira=carro.lado_chiquinquira,
            )
        )
        plan.cambios.append(Cambio(carro.numero, "activo", "True", "False"))
    return plan


# --------------------------------------------------------------------- zonas


@dataclass
class PlanZonas:
    nuevas: list[Zona] = field(default_factory=list)
    solo_en_base: list[tuple[str, int]] = field(default_factory=list)
    nombres_malformados: list[str] = field(default_factory=list)


def planear_zonas(
    nombres_archivo: Iterable[str],
    zonas_base: Sequence[Zona],
    clientes_por_zona: Mapping[str, int],
) -> PlanZonas:
    """Crea las zonas nuevas de la maestra; las que ya no aparecen solo se listan.

    Desactivarlas en esta corrida sería peligroso: una zona que hoy no tiene
    clientes puede seguir en el repertorio de un carro, y la lista con su número de
    clientes es justo lo que hace falta para decidirlo a mano.
    """
    plan = PlanZonas()
    en_base = {zona.nombre for zona in zonas_base}
    vistos: set[str] = set()
    for crudo in nombres_archivo:
        nombre = normalizar_nombre_zona(crudo)
        if not nombre or nombre in vistos:
            continue
        vistos.add(nombre)
        # El prefijo "(MUNICIPIO):" sin cerrar no lo arregla la normalización: el
        # parseo lo tolera, pero el nombre torcido se reporta para decidirlo a mano.
        if nombre.count("(") != nombre.count(")"):
            plan.nombres_malformados.append(nombre)
        if nombre not in en_base:
            plan.nuevas.append(crear_zona(nombre))
    for zona in zonas_base:
        if zona.nombre not in vistos:
            plan.solo_en_base.append((zona.nombre, clientes_por_zona.get(zona.nombre, 0)))
    plan.solo_en_base.sort(key=lambda par: (-par[1], par[0]))
    return plan


# ------------------------------------------------------------------ clientes


@dataclass(frozen=True)
class DatosCompletos:
    """Lo que aporta la hoja MAESTRA COMPLETA por código: documento y razón social."""

    documento: str | None = None
    razon_social: str | None = None


@dataclass(frozen=True)
class FilaCliente:
    """Una fila de MAESTRA, ya sin depender del lector de Excel."""

    codigo: str
    direccion: str | None = None
    ciudad: str | None = None
    barrio: str | None = None
    ruta: str | None = None


@dataclass
class PlanClientes:
    nuevos: list[Cliente] = field(default_factory=list)
    actualizados: list[Cliente] = field(default_factory=list)
    cambios_de_zona: list[Cambio] = field(default_factory=list)
    cambios_de_ubicacion: list[Cambio] = field(default_factory=list)
    rellenados: list[Cambio] = field(default_factory=list)
    solo_en_base: list[str] = field(default_factory=list)
    zonas_no_encontradas: list[Cambio] = field(default_factory=list)
    duplicados_en_archivo: int = 0
    sin_cambios: int = 0

    @property
    def a_guardar(self) -> list[Cliente]:
        return self.nuevos + self.actualizados


def planear_clientes(
    filas: Sequence[FilaCliente],
    completos: Mapping[str, DatosCompletos],
    clientes_base: Sequence[Cliente],
    zonas_por_nombre: Mapping[str, Zona],
) -> PlanClientes:
    """Upsert por código, sin pisar lo que la app ya sabe.

    Dos asimetrías deliberadas: ``documento`` y ``razon_social`` solo se **rellenan**
    cuando están vacíos —si alguien los corrigió en la app, la hoja no los pisa—,
    mientras que zona, ciudad, barrio y dirección sí se actualizan, porque ahí la
    maestra es la fuente y se corrige a diario.
    """
    plan = PlanClientes()
    por_codigo = {cliente.codigo: cliente for cliente in clientes_base}
    vistos: set[str] = set()

    for fila in filas:
        if fila.codigo in vistos:
            plan.duplicados_en_archivo += 1
            continue
        vistos.add(fila.codigo)
        completo = completos.get(fila.codigo, DatosCompletos())
        nombre_zona = normalizar_nombre_zona(fila.ruta) if fila.ruta else ""
        zona = zonas_por_nombre.get(nombre_zona)
        actual = por_codigo.get(fila.codigo)

        if nombre_zona and zona is None:
            plan.zonas_no_encontradas.append(Cambio(fila.codigo, "zona inexistente", None, nombre_zona))

        if actual is None:
            plan.nuevos.append(
                Cliente(
                    codigo=fila.codigo,
                    direccion=fila.direccion,
                    barrio=fila.barrio,
                    ciudad=fila.ciudad,
                    zona=zona,
                    documento=completo.documento,
                    razon_social=completo.razon_social,
                )
            )
            continue

        # La zona vieja se conserva si la nueva no se pudo resolver: dejar al
        # cliente sin zona lo mandaría al pozo de los #N/D por un error de catálogo.
        zona_final = zona or actual.zona
        documento = actual.documento or completo.documento
        razon_social = actual.razon_social or completo.razon_social

        if (actual.zona.nombre if actual.zona else None) != (zona_final.nombre if zona_final else None):
            plan.cambios_de_zona.append(Cambio(fila.codigo, "zona", _texto(actual.zona), _texto(zona_final)))
        plan.cambios_de_ubicacion.extend(
            _comparar(
                fila.codigo,
                {
                    "ciudad": (actual.ciudad, fila.ciudad),
                    "barrio": (actual.barrio, fila.barrio),
                    "direccion": (actual.direccion, fila.direccion),
                },
            )
        )
        if not actual.documento and completo.documento:
            plan.rellenados.append(Cambio(fila.codigo, "documento", None, completo.documento))
        if not actual.razon_social and completo.razon_social:
            plan.rellenados.append(Cambio(fila.codigo, "razon_social", None, completo.razon_social))

        candidato = Cliente(
            codigo=fila.codigo,
            direccion=fila.direccion,
            barrio=fila.barrio,
            ciudad=fila.ciudad,
            zona=zona_final,
            documento=documento,
            razon_social=razon_social,
            dia_visita=actual.dia_visita,
            activo=actual.activo,
        )
        if candidato == actual:
            plan.sin_cambios += 1
        else:
            plan.actualizados.append(candidato)

    plan.solo_en_base = sorted(codigo for codigo in por_codigo if codigo not in vistos)
    return plan


# ------------------------------------------------- correcciones y overrides


@dataclass
class PlanCorrecciones:
    nuevas: list[CorreccionUbicacion] = field(default_factory=list)
    actualizadas: list[CorreccionUbicacion] = field(default_factory=list)
    cambios: list[Cambio] = field(default_factory=list)
    solo_en_base: list[str] = field(default_factory=list)
    sin_cambios: int = 0

    @property
    def a_guardar(self) -> list[CorreccionUbicacion]:
        return self.nuevas + self.actualizadas


def planear_correcciones(
    filas: Sequence[CorreccionUbicacion], base: Sequence[CorreccionUbicacion]
) -> PlanCorrecciones:
    plan = PlanCorrecciones()
    por_codigo = {c.cliente_codigo: c for c in base}
    vistos: set[str] = set()
    for fila in filas:
        if fila.cliente_codigo in vistos:
            continue
        vistos.add(fila.cliente_codigo)
        actual = por_codigo.get(fila.cliente_codigo)
        if actual is None:
            plan.nuevas.append(fila)
            plan.cambios.append(
                Cambio(fila.cliente_codigo, "corrección nueva", None, _texto(fila.ciudad_real))
            )
        elif actual != fila:
            plan.actualizadas.append(fila)
            plan.cambios.extend(
                _comparar(
                    fila.cliente_codigo,
                    {
                        "ciudad_real": (actual.ciudad_real, fila.ciudad_real),
                        "barrio_real": (actual.barrio_real, fila.barrio_real),
                    },
                )
            )
        else:
            plan.sin_cambios += 1
    plan.solo_en_base = sorted(codigo for codigo in por_codigo if codigo not in vistos)
    return plan


@dataclass
class PlanOverrides:
    nuevos: list[OverrideZona] = field(default_factory=list)
    actualizados: list[OverrideZona] = field(default_factory=list)
    cambios: list[Cambio] = field(default_factory=list)
    solo_en_base: list[str] = field(default_factory=list)
    zonas_no_encontradas: list[Cambio] = field(default_factory=list)
    sin_cambios: int = 0

    @property
    def a_guardar(self) -> list[OverrideZona]:
        return self.nuevos + self.actualizados


def planear_overrides(
    filas: Sequence[OverrideZona],
    base: Sequence[OverrideZona],
    nombres_de_zona: Iterable[str],
) -> PlanOverrides:
    """Igual que el resto, con un filtro propio: la hoja "martha ojo" está llena de
    restos de fórmulas, así que un override cuya zona no existe no se guarda (la FK
    lo rechazaría) sino que se reporta."""
    plan = PlanOverrides()
    validas = set(nombres_de_zona)
    por_codigo = {o.cliente_codigo: o for o in base}
    vistos: set[str] = set()
    for fila in filas:
        if fila.cliente_codigo in vistos:
            continue
        nombre = normalizar_nombre_zona(fila.zona_nombre)
        if nombre not in validas:
            plan.zonas_no_encontradas.append(Cambio(fila.cliente_codigo, "zona inexistente", None, nombre))
            continue
        vistos.add(fila.cliente_codigo)
        normalizado = OverrideZona(cliente_codigo=fila.cliente_codigo, zona_nombre=nombre)
        actual = por_codigo.get(fila.cliente_codigo)
        if actual is None:
            plan.nuevos.append(normalizado)
            plan.cambios.append(Cambio(fila.cliente_codigo, "override nuevo", None, nombre))
        elif actual.zona_nombre != nombre:
            plan.actualizados.append(normalizado)
            plan.cambios.append(Cambio(fila.cliente_codigo, "zona", actual.zona_nombre, nombre))
        else:
            plan.sin_cambios += 1
    plan.solo_en_base = sorted(codigo for codigo in por_codigo if codigo not in vistos)
    return plan
