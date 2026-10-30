"""Heredar el repertorio de las zonas viejas a las nuevas, por mapeo de clientes.

En octubre de 2026 la maestra pasó de 193 zonas a 101 y unos 3.600 clientes
cambiaron de zona. El repertorio —qué carro atiende qué zona cada día, con cuántas
observaciones— estaba sembrado con los nombres viejos, así que de golpe quedó
apuntando a zonas que ya no tienen clientes. Sembrarlo de nuevo con una sola
semana de archivos da "visto 1 vez" en casi todo y pierde meses de costumbre.

La idea: si el 60 % de los clientes de la zona nueva Z venían de la vieja A y el
40 % de B, el repertorio de Z se estima mezclando los de A y B con esos pesos.

Tres cosas que este módulo NO hace, a propósito:

- **No pisa lo sembrado.** Si Z ya tiene algún par ese día, el día entero se
  respeta: lo que la operación hizo con el nombre nuevo manda sobre la
  estimación. La herencia solo tapa huecos.
- **No inventa pares.** Solo propaga los que existen en los orígenes. Un par de
  origen con frecuencia 0 hereda 0, porque un 0 es una decisión deliberada
  ("este carro no atiende esta zona ese día") y no la ausencia de información.
- **No toca las zonas especiales.** Un cliente que pide esporádicamente y en
  grande no tiene costumbre que heredar: se despacha con el vehículo que convenga
  ese día.
"""

from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field

from planeacion.application.puertos.salida.repositorios import ParRepertorio
from planeacion.domain.modelo import nombre_sin_prefijo

# La zona vieja con la que el mapeo marca al cliente que no estaba en la base.
# No tiene repertorio que aportar, así que su peso diluye la suma sin sumar nada,
# que es exactamente lo que corresponde: de esos clientes no se sabe nada.
SIN_ORIGEN = "(cliente nuevo)"

ENCABEZADO_MAPEO = ("zona_nueva", "zona_vieja", "clientes", "total_de_la_zona", "fraccion")
# El respaldo que escribe `planeacion-sembrar-repertorio` antes de vaciar.
ENCABEZADO_RESPALDO = ("numero_carro", "nombre_zona", "dia_semana", "frecuencia")


@dataclass(frozen=True)
class Origen:
    """Una zona vieja que aporta clientes a una zona nueva, con su peso."""

    zona_nueva: str
    zona_vieja: str
    clientes: int
    total_de_la_zona: int

    @property
    def peso(self) -> float:
        if self.total_de_la_zona <= 0:
            return 0.0
        return self.clientes / self.total_de_la_zona


@dataclass
class Herencia:
    """Lo que la herencia escribiría, y lo que decidió no tocar."""

    pares: list[ParRepertorio] = field(default_factory=list)
    # Zona nueva -> días que ya tenían repertorio propio y no se tocaron.
    dias_respetados: dict[str, set[str]] = field(default_factory=dict)
    # Zonas nuevas que quedan sin ningún par: ni sembrado ni heredado. Son las que
    # hay que mirar a mano, porque sin par no tienen carro elegible.
    sin_ningun_par: list[str] = field(default_factory=list)
    especiales_ignoradas: list[str] = field(default_factory=list)

    @property
    def pares_por_dia(self) -> dict[str, int]:
        conteo: dict[str, int] = {}
        for par in self.pares:
            conteo[par.dia_semana] = conteo.get(par.dia_semana, 0) + 1
        return conteo


def leer_mapeo(lineas: Iterable[Sequence[str]]) -> list[Origen]:
    """El CSV de `planeacion-resincronizar`, sin su encabezado.

    Las filas con conteos ilegibles se descartan en vez de reventar: el archivo lo
    puede haber tocado alguien en Excel y una fila rota no justifica perder las
    otras doscientas.
    """
    origenes: list[Origen] = []
    for fila in lineas:
        if len(fila) < 4 or tuple(campo.strip() for campo in fila[:5]) == ENCABEZADO_MAPEO:
            continue
        try:
            clientes = int(fila[2])
            total = int(fila[3])
        except ValueError:
            continue
        if not fila[0].strip() or not fila[1].strip():
            continue
        origenes.append(
            Origen(
                zona_nueva=fila[0].strip(),
                zona_vieja=fila[1].strip(),
                clientes=clientes,
                total_de_la_zona=total,
            )
        )
    return origenes


def heredar(
    origenes: Sequence[Origen],
    frecuencias: Mapping[ParRepertorio, int],
    especiales: Collection[str] = (),
    frecuencias_origen: Mapping[ParRepertorio, int] | None = None,
) -> Herencia:
    """Qué pares de repertorio le tocarían a cada zona nueva.

    Son DOS entradas, y conviene no confundirlas:

    - ``frecuencias``: el repertorio tal como está hoy en la base. Decide qué días
      ya están cubiertos y por lo tanto no se tocan.
    - ``frecuencias_origen``: de dónde heredar. Por defecto las mismas, pero la
      resiembra con ``--vaciar`` **borra los pares de las zonas viejas**, que son
      justamente el origen: ahí hay que pasarle el respaldo anterior al vaciado.
      Separarlas es lo que permite vaciar y heredar en la misma corrida.
    """
    del_origen = frecuencias if frecuencias_origen is None else frecuencias_origen
    nombres_especiales = {nombre_sin_prefijo(nombre).upper() for nombre in especiales}
    herencia = Herencia()

    # Lo que hay hoy: qué zona tiene pares en qué días (lo que no se toca).
    dias_con_pares: dict[str, set[str]] = {}
    for par in frecuencias:
        dias_con_pares.setdefault(par.nombre_zona, set()).add(par.dia_semana)
    # De dónde heredar, indexado por (zona de origen, día).
    por_zona_dia: dict[tuple[str, str], dict[str, int]] = {}
    for par, frecuencia in del_origen.items():
        por_zona_dia.setdefault((par.nombre_zona, par.dia_semana), {})[par.numero_carro] = frecuencia

    for zona_nueva, sus_origenes in _por_zona_nueva(origenes).items():
        if nombre_sin_prefijo(zona_nueva).upper() in nombres_especiales:
            herencia.especiales_ignoradas.append(zona_nueva)
            continue

        utiles = [origen for origen in sus_origenes if origen.zona_vieja != SIN_ORIGEN]
        dias_propios = dias_con_pares.get(zona_nueva, set())
        if dias_propios:
            herencia.dias_respetados[zona_nueva] = set(dias_propios)

        heredados = 0
        for dia in _dias_de(utiles, por_zona_dia):
            # Lo sembrado con el nombre nuevo manda: si la zona ya tiene algún par
            # ese día, el día entero se respeta.
            if dia in dias_propios:
                continue
            for numero_carro, frecuencia in _mezclar(utiles, dia, por_zona_dia).items():
                herencia.pares.append(ParRepertorio(numero_carro, zona_nueva, dia, frecuencia=frecuencia))
                heredados += 1

        if not dias_propios and not heredados:
            herencia.sin_ningun_par.append(zona_nueva)

    herencia.pares.sort(key=lambda par: (par.dia_semana, par.nombre_zona, par.numero_carro))
    herencia.sin_ningun_par.sort()
    herencia.especiales_ignoradas.sort()
    return herencia


def _por_zona_nueva(origenes: Sequence[Origen]) -> dict[str, list[Origen]]:
    agrupados: dict[str, list[Origen]] = {}
    for origen in origenes:
        agrupados.setdefault(origen.zona_nueva, []).append(origen)
    return agrupados


def _dias_de(
    origenes: Sequence[Origen], por_zona_dia: Mapping[tuple[str, str], Mapping[str, int]]
) -> list[str]:
    """Los días en que alguno de los orígenes tiene repertorio."""
    dias = {dia for (zona, dia) in por_zona_dia if any(origen.zona_vieja == zona for origen in origenes)}
    return sorted(dias)


def _mezclar(
    origenes: Sequence[Origen],
    dia: str,
    por_zona_dia: Mapping[tuple[str, str], Mapping[str, int]],
) -> dict[str, int]:
    """La frecuencia heredada de cada carro para un día.

    Solo aparecen los carros que ya tenían par en alguna zona de origen: la
    herencia propaga lo que existe, no estrena carros en la zona. Un par que
    existía con 0 hereda 0, porque ese 0 lo puso alguien a propósito.
    """
    suma: dict[str, float] = {}
    for origen in origenes:
        for numero_carro, frecuencia in por_zona_dia.get((origen.zona_vieja, dia), {}).items():
            suma[numero_carro] = suma.get(numero_carro, 0.0) + origen.peso * frecuencia
    # Mínimo 1 donde la suma es positiva: redondear 0,4 a 0 convertiría "este
    # carro la atiende poco" en "este carro no la atiende", que es otra cosa.
    return {numero_carro: max(1, round(total)) if total > 0 else 0 for numero_carro, total in suma.items()}


def leer_respaldo(lineas: Iterable[Sequence[str]]) -> dict[ParRepertorio, int]:
    """El CSV de respaldo del repertorio → frecuencias, para heredar de ahí.

    Hace falta porque la resiembra con ``--vaciar`` borra los pares de las zonas
    viejas, que son el origen de la herencia: sin este archivo, heredar después de
    vaciar no encontraría nada de dónde heredar y saldría vacío sin dar error.
    """
    frecuencias: dict[ParRepertorio, int] = {}
    for fila in lineas:
        if len(fila) < 4 or tuple(campo.strip() for campo in fila[:4]) == ENCABEZADO_RESPALDO:
            continue
        carro, zona, dia = (campo.strip() for campo in fila[:3])
        if not carro or not zona or not dia:
            continue
        try:
            frecuencia = int(fila[3])
        except ValueError:
            continue
        frecuencias[ParRepertorio(carro, zona, dia)] = frecuencia
    return frecuencias
