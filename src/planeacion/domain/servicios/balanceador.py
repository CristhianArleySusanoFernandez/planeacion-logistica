"""Balanceador heurístico: reparte las zonas del día entre los carros del municipio.

Puro (solo stdlib). Arranca de la planeación previa del mismo día de semana
(warm-start) o de un round-robin por peso descendente, fija las reglas duras y
mejora con movimientos e intercambios de zonas entre carros del mismo municipio
mientras baje la función de costo:

    costo(municipio) = w_clientes * cv(clientes por carro)
                     + w_pesos * cv(pesos por carro)
                     + w_frecuencia * penalizacion media por costumbre

El tercer término es el desempate por costumbre: entre los carros que TIENEN
permitida una zona, prefiere al que históricamente la atiende (ver
``penalizaciones_por_frecuencia``). Es deliberadamente liviano — mueve
decisiones marginales, no debe sobrecargar un carro; con ``w_frecuencia`` en 0
o sin frecuencias el balanceo se comporta exactamente como antes.

Repertorio (carro → zonas permitidas): cuando viene configurado, una zona solo
puede caer en un carro que la tenga permitida — en el reparto inicial, en el
warm-start y en cada movimiento/intercambio de la mejora. Una zona "viajera"
cuyo único carro elegible es de otro municipio se balancea en el pool de ese
carro (p. ej. RAQUIRA, de OTROS, viaja en el carro 2 de Chiquinquirá); si ningún
carro activo la permite queda en ``zonas_sin_carro``. Con repertorio vacío
(base sin configurar) todo funciona como antes.

Regla dura de Chiquinquirá: una zona del sur solo puede caer en una ruta del
sur, y lo mismo el norte. El lado es un DATO de la ruta (``carro.lado_chiquinquira``,
que sale de su zona principal en la hoja BASE), no una posición en el pool: el
municipio tiene cuatro rutas —1 y 2 al sur, 3 y 4 al norte— y la regla aplica al
par de cada lado. Entre las rutas del lado correcto deciden el repertorio y el
balance, que es lo que hace el resto del servicio; medido sobre septiembre y
octubre de 2026, el lado se respeta en 81 de 93 asignaciones pero el reparto
dentro del lado se mueve todo el tiempo. La regla prevalece sobre el repertorio.
Si ninguna ruta del pool trae lado (base sin configurar), no hay regla que
aplicar y manda el balance, como con el repertorio vacío.
"""

from collections.abc import Callable, Mapping, Sequence
from decimal import Decimal
from statistics import pstdev

from planeacion.domain.errores import MovimientoInvalido, SinCarrosParaMunicipio
from planeacion.domain.modelo import (
    CargaCarro,
    Carro,
    MetricasDesbalance,
    ReglasBalanceo,
    ResultadoBalanceo,
    ZonaAgregada,
)
from planeacion.domain.modelo.balanceo import (
    REGLAS_POR_DEFECTO,
    Frecuencias,
    Repertorio,
    penalizaciones_por_frecuencia,
    zona_permitida,
)

# (número de carro, nombre de zona) → cuánto penaliza esa combinación, en [0, 1).
Penalizaciones = Mapping[tuple[str, str], float]

_MEJORA_MINIMA = 1e-9


def _cv(valores: Sequence[float]) -> float:
    """Coeficiente de variación poblacional; sin datos o con media 0 vale 0."""
    if not valores:
        return 0.0
    media = sum(valores) / len(valores)
    if media == 0:
        return 0.0
    return pstdev(valores) / media


def calcular_metricas(municipio: str, cargas: Sequence[CargaCarro]) -> MetricasDesbalance:
    clientes = [carga.clientes for carga in cargas]
    pesos = [carga.pesos for carga in cargas]
    return MetricasDesbalance(
        municipio=municipio,
        rango_clientes=max(clientes) - min(clientes) if clientes else 0,
        rango_pesos=max(pesos) - min(pesos) if pesos else Decimal("0"),
        cv_clientes=_cv([float(c) for c in clientes]),
        cv_pesos=_cv([float(p) for p in pesos]),
    )


def _penalizacion_media(cargas: Sequence[CargaCarro], penalizaciones: Penalizaciones) -> float:
    """Promedio de la penalización de las zonas repartidas, en [0, 1).

    Va promediado y no sumado para quedar en la misma escala que los CV: así
    ``w_frecuencia`` es comparable con ``w_clientes`` y ``w_pesos`` sin depender
    de cuántas zonas tenga el municipio.
    """
    zonas = [(carga.carro.numero, zona.zona.nombre) for carga in cargas for zona in carga.zonas]
    if not zonas:
        return 0.0
    return sum(penalizaciones.get(par, 0.0) for par in zonas) / len(zonas)


def calcular_costo(
    cargas: Sequence[CargaCarro],
    reglas: ReglasBalanceo,
    penalizaciones: Penalizaciones | None = None,
) -> float:
    """La función que la heurística minimiza dentro de cada municipio."""
    costo = reglas.w_clientes * _cv([float(carga.clientes) for carga in cargas]) + reglas.w_pesos * _cv(
        [float(carga.pesos) for carga in cargas]
    )
    if penalizaciones and reglas.w_frecuencia:
        costo += reglas.w_frecuencia * _penalizacion_media(cargas, penalizaciones)
    return costo


def _lado_compatible(zona: ZonaAgregada, carro: Carro) -> bool:
    """¿Puede esta zona caer en esta ruta sin romper la regla de Chiquinquirá?

    Las dos puertas de escape son deliberadas: una zona sin lado (todo lo que no
    es Chiquinquirá) va a donde sea, y una ruta sin lado configurado acepta todo,
    para que una base a medio configurar no se quede sin reparto.
    """
    lado_zona = zona.zona.regla_chiquinquira
    if lado_zona is None or carro.lado_chiquinquira is None:
        return True
    return carro.lado_chiquinquira is lado_zona


class Balanceador:
    def balancear(
        self,
        zonas_agregadas: Sequence[ZonaAgregada],
        carros_por_municipio: Mapping[str, Sequence[Carro]],
        asignacion_previa: Mapping[str, str] | None,
        reglas: ReglasBalanceo = REGLAS_POR_DEFECTO,
        repertorio: Repertorio | None = None,
        frecuencias: Frecuencias | None = None,
    ) -> ResultadoBalanceo:
        # Un carro con repertorio declarado pero vacío cuenta como no configurado.
        repertorio_limpio = {n: frozenset(zs) for n, zs in (repertorio or {}).items() if zs}
        penalizaciones = penalizaciones_por_frecuencia(repertorio_limpio, frecuencias or {})
        municipio_de_carro = {
            carro.numero: municipio for municipio, carros in carros_por_municipio.items() for carro in carros
        }
        zonas_por_municipio, zonas_sin_carro = self._agrupar_zonas(
            zonas_agregadas, municipio_de_carro, repertorio_limpio
        )

        cargas_por_municipio: dict[str, list[CargaCarro]] = {}
        metricas_iniciales: dict[str, MetricasDesbalance] = {}
        metricas_finales: dict[str, MetricasDesbalance] = {}
        desde_historico = False

        for municipio, zonas in sorted(zonas_por_municipio.items()):
            carros = list(carros_por_municipio.get(municipio, []))
            if not carros:
                raise SinCarrosParaMunicipio(
                    f"el municipio {municipio} tiene {len(zonas)} zonas con carga pero ningún carro"
                )
            cargas, uso_previa = self._inicializar(zonas, carros, asignacion_previa, repertorio_limpio)
            desde_historico = desde_historico or uso_previa
            self._aplicar_reglas_duras(cargas, repertorio_limpio)
            metricas_iniciales[municipio] = calcular_metricas(municipio, cargas)
            self._mejorar(cargas, reglas, repertorio_limpio, penalizaciones)
            metricas_finales[municipio] = calcular_metricas(municipio, cargas)
            cargas_por_municipio[municipio] = cargas

        return ResultadoBalanceo(
            cargas_por_municipio=cargas_por_municipio,
            metricas_iniciales=metricas_iniciales,
            metricas_finales=metricas_finales,
            desde_historico=desde_historico,
            zonas_sin_carro=zonas_sin_carro,
            repertorio=repertorio_limpio,
        )

    def _agrupar_zonas(
        self,
        zonas: Sequence[ZonaAgregada],
        municipio_de_carro: Mapping[str, str],
        repertorio: Repertorio,
    ) -> tuple[dict[str, list[ZonaAgregada]], list[ZonaAgregada]]:
        """Cada zona va al pool donde se puede balancear; sin carro elegible, afuera."""
        grupos: dict[str, list[ZonaAgregada]] = {}
        sin_carro: list[ZonaAgregada] = []
        for zona in zonas:
            municipio = self._municipio_de_balanceo(zona, municipio_de_carro, repertorio)
            if municipio is None:
                sin_carro.append(zona)
            else:
                grupos.setdefault(municipio, []).append(zona)
        return grupos, sin_carro

    def _municipio_de_balanceo(
        self,
        zona: ZonaAgregada,
        municipio_de_carro: Mapping[str, str],
        repertorio: Repertorio,
    ) -> str | None:
        """Sin repertorio, el municipio propio. Con repertorio, el municipio propio si
        algún carro suyo la permite; si solo la permiten carros de otro municipio, la
        zona "viaja" al pool de esos carros; sin ningún carro elegible → None."""
        propio = zona.zona.municipio.nombre
        if not repertorio:
            return propio
        municipios_elegibles = [
            municipio_de_carro[numero]
            for numero, permitidas in repertorio.items()
            if zona.zona.nombre in permitidas and numero in municipio_de_carro
        ]
        if not municipios_elegibles:
            return None
        if propio in municipios_elegibles:
            return propio
        # Determinista: el municipio con más carros elegibles; empate → alfabético.
        return min(set(municipios_elegibles), key=lambda m: (-municipios_elegibles.count(m), m))

    def _inicializar(
        self,
        zonas: Sequence[ZonaAgregada],
        carros: Sequence[Carro],
        asignacion_previa: Mapping[str, str] | None,
        repertorio: Repertorio,
    ) -> tuple[list[CargaCarro], bool]:
        """Warm-start desde la previa si existe; si no, round-robin por peso descendente."""
        cargas = [CargaCarro(carro=carro) for carro in carros]
        por_numero = {carga.carro.numero: carga for carga in cargas}
        ordenadas = sorted(zonas, key=lambda z: z.pesos, reverse=True)

        uso_previa = False
        nuevas: list[ZonaAgregada] = []
        if asignacion_previa:
            for zona in ordenadas:
                numero_previo = asignacion_previa.get(zona.zona.nombre)
                if (
                    numero_previo is not None
                    and numero_previo in por_numero
                    and zona_permitida(repertorio, zona.zona.nombre, numero_previo)
                ):
                    por_numero[numero_previo].agregar(zona)
                    uso_previa = True
                else:
                    # Zona nueva, con carro previo fuera del pool, o cuyo carro
                    # previo ya no la tiene permitida (Rudy cambió el repertorio).
                    nuevas.append(zona)
        else:
            nuevas = list(ordenadas)

        if uso_previa or repertorio:
            # Cada nueva va al carro ELEGIBLE menos cargado (greedy). El grupo
            # garantiza al menos un elegible por zona.
            for zona in nuevas:
                elegibles = [
                    carga
                    for carga in cargas
                    if zona_permitida(repertorio, zona.zona.nombre, carga.carro.numero)
                ]
                menos_cargado = min(elegibles, key=lambda c: (c.pesos, c.clientes))
                menos_cargado.agregar(zona)
        else:
            for indice, zona in enumerate(nuevas):
                cargas[indice % len(cargas)].agregar(zona)

        return cargas, uso_previa

    def _aplicar_reglas_duras(self, cargas: list[CargaCarro], repertorio: Repertorio) -> None:
        """Chiquinquirá: devuelve al lado correcto las zonas que cayeron del otro.

        Solo corrige lo que está mal; una zona que ya está en una ruta de su lado
        no se mueve, y el reparto dentro del lado lo sigue decidiendo ``_mejorar``.
        Entre las rutas candidatas elige la menos cargada que además tenga la zona
        en su repertorio, y si ninguna la tiene, la menos cargada del lado: la
        regla dura prevalece sobre el repertorio, no al revés.
        """
        if len(cargas) < 2:
            return  # con una sola ruta no hay a dónde forzar
        for carga in cargas:
            for zona in list(carga.zonas):
                if _lado_compatible(zona, carga.carro):
                    continue
                candidatas = [otra for otra in cargas if _lado_compatible(zona, otra.carro)]
                if not candidatas:
                    continue  # el lado no existe en este pool: mejor dejarla donde está
                con_repertorio = [
                    otra
                    for otra in candidatas
                    if zona_permitida(repertorio, zona.zona.nombre, otra.carro.numero)
                ]
                objetivo = min(con_repertorio or candidatas, key=lambda c: (c.pesos, c.clientes))
                carga.quitar(zona.zona.nombre)
                objetivo.agregar(zona)

    def _mejorar(
        self,
        cargas: list[CargaCarro],
        reglas: ReglasBalanceo,
        repertorio: Repertorio,
        penalizaciones: Penalizaciones,
    ) -> None:
        """Best-improvement: en cada pasada ejecuta el mejor movimiento/intercambio que baje el costo."""
        for _ in range(reglas.max_iteraciones):
            mejor = self._mejor_movimiento(cargas, reglas, repertorio, penalizaciones)
            if mejor is None:
                return
            mejor()

    def _mejor_movimiento(
        self,
        cargas: list[CargaCarro],
        reglas: ReglasBalanceo,
        repertorio: Repertorio,
        penalizaciones: Penalizaciones,
    ) -> Callable[[], None] | None:
        costo_actual = calcular_costo(cargas, reglas, penalizaciones)
        mejor_costo = costo_actual - _MEJORA_MINIMA
        mejor_accion: Callable[[], None] | None = None

        for indice_a, origen in enumerate(cargas):
            for indice_b, destino in enumerate(cargas):
                if origen is destino:
                    continue
                for zona in list(origen.zonas):
                    if not _lado_compatible(zona, destino.carro):
                        continue
                    permitida_en_destino = zona_permitida(repertorio, zona.zona.nombre, destino.carro.numero)
                    # Probar mover la zona de A a B (y revertir).
                    if permitida_en_destino:
                        costo = self._costo_si_mueve(cargas, reglas, origen, destino, zona, penalizaciones)
                        if costo < mejor_costo:
                            mejor_costo = costo
                            mejor_accion = self._accion_mover(origen, destino, zona)
                    # Probar intercambios solo en una dirección (A<B) para no evaluar doble.
                    if indice_a < indice_b and permitida_en_destino:
                        for zona_b in list(destino.zonas):
                            if not _lado_compatible(zona_b, origen.carro) or not zona_permitida(
                                repertorio, zona_b.zona.nombre, origen.carro.numero
                            ):
                                continue
                            costo = self._costo_si_intercambia(
                                cargas, reglas, origen, destino, zona, zona_b, penalizaciones
                            )
                            if costo < mejor_costo:
                                mejor_costo = costo
                                mejor_accion = self._accion_intercambiar(origen, destino, zona, zona_b)
        return mejor_accion

    def _costo_si_mueve(
        self,
        cargas: list[CargaCarro],
        reglas: ReglasBalanceo,
        origen: CargaCarro,
        destino: CargaCarro,
        zona: ZonaAgregada,
        penalizaciones: Penalizaciones,
    ) -> float:
        origen.quitar(zona.zona.nombre)
        destino.agregar(zona)
        costo = calcular_costo(cargas, reglas, penalizaciones)
        destino.quitar(zona.zona.nombre)
        origen.agregar(zona)
        return costo

    def _costo_si_intercambia(
        self,
        cargas: list[CargaCarro],
        reglas: ReglasBalanceo,
        origen: CargaCarro,
        destino: CargaCarro,
        zona_a: ZonaAgregada,
        zona_b: ZonaAgregada,
        penalizaciones: Penalizaciones,
    ) -> float:
        origen.quitar(zona_a.zona.nombre)
        destino.quitar(zona_b.zona.nombre)
        origen.agregar(zona_b)
        destino.agregar(zona_a)
        costo = calcular_costo(cargas, reglas, penalizaciones)
        origen.quitar(zona_b.zona.nombre)
        destino.quitar(zona_a.zona.nombre)
        origen.agregar(zona_a)
        destino.agregar(zona_b)
        return costo

    @staticmethod
    def _accion_mover(origen: CargaCarro, destino: CargaCarro, zona: ZonaAgregada) -> Callable[[], None]:
        def ejecutar() -> None:
            origen.quitar(zona.zona.nombre)
            destino.agregar(zona)

        return ejecutar

    @staticmethod
    def _accion_intercambiar(
        origen: CargaCarro, destino: CargaCarro, zona_a: ZonaAgregada, zona_b: ZonaAgregada
    ) -> Callable[[], None]:
        def ejecutar() -> None:
            origen.quitar(zona_a.zona.nombre)
            destino.quitar(zona_b.zona.nombre)
            origen.agregar(zona_b)
            destino.agregar(zona_a)

        return ejecutar


class AjustadorDeAsignacion:
    """El override manual de Rudy: mover una zona a otro carro que pueda atenderla.

    Sin repertorio configurado rige la regla clásica (solo carros del mismo
    municipio); con repertorio, el destino válido es cualquier carro de la
    planeación que tenga la zona permitida (incluye a las viajeras cruzadas).
    Una zona de Chiquinquirá sí se puede mover, pero solo entre rutas de su lado.
    """

    def mover(self, resultado: ResultadoBalanceo, nombre_zona: str, numero_carro: str) -> ResultadoBalanceo:
        """Muta el resultado (mueve la zona y recalcula las métricas afectadas)."""
        municipio_origen, origen, zona = self._buscar_zona(resultado, nombre_zona)
        encontrado = self._buscar_carro(resultado, numero_carro)
        if encontrado is None:
            raise MovimientoInvalido(f"el carro {numero_carro} no está en la planeación")
        municipio_destino, destino = encontrado
        if not _lado_compatible(zona, destino.carro):
            regla = zona.zona.regla_chiquinquira
            raise MovimientoInvalido(
                f"{nombre_zona} es del {regla.value if regla else '?'} de Chiquinquirá y el carro "
                f"{numero_carro} reparte del otro lado (regla dura)"
            )
        if destino is origen:
            raise MovimientoInvalido(f"{nombre_zona} ya está en el carro {numero_carro}")
        if resultado.repertorio:
            if not resultado.carro_permite(numero_carro, nombre_zona):
                raise MovimientoInvalido(
                    f"el carro {numero_carro} no tiene permitida la zona {nombre_zona} "
                    "(configúrala en Configuración → Zonas por carro)"
                )
        elif municipio_destino != municipio_origen:
            raise MovimientoInvalido(
                f"el carro {numero_carro} no está en el pool de {municipio_origen} "
                f"(solo se puede mover dentro del mismo municipio)"
            )

        origen.quitar(nombre_zona)
        destino.agregar(zona)
        for municipio in {municipio_origen, municipio_destino}:
            resultado.metricas_finales[municipio] = calcular_metricas(
                municipio, resultado.cargas_por_municipio[municipio]
            )
        return resultado

    def _buscar_zona(
        self, resultado: ResultadoBalanceo, nombre_zona: str
    ) -> tuple[str, CargaCarro, ZonaAgregada]:
        for municipio, cargas in resultado.cargas_por_municipio.items():
            for carga in cargas:
                for zona in carga.zonas:
                    if zona.zona.nombre == nombre_zona:
                        return municipio, carga, zona
        raise MovimientoInvalido(f"la zona {nombre_zona!r} no está en la planeación")

    def _buscar_carro(self, resultado: ResultadoBalanceo, numero_carro: str) -> tuple[str, CargaCarro] | None:
        for municipio, cargas in resultado.cargas_por_municipio.items():
            for carga in cargas:
                if carga.carro.numero == numero_carro:
                    return municipio, carga
        return None
