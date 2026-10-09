"""Caso de uso: generar la planeación del día (pivote + warm-start + balanceo).

No persiste nada por sí solo: la máquina propone y Rudy decide. ``guardar`` se
llama aparte, cuando ella confirma en el CLI o en la UI.
"""

import logging
from datetime import date
from pathlib import Path

from planeacion.application.dto.planeacion import PlaneacionCompleta
from planeacion.application.puertos.entrada.generar_pivote import GenerarPivotePorZona
from planeacion.application.puertos.salida.repositorios import (
    RepositorioCarros,
    RepositorioCarroZonas,
    RepositorioParametros,
    RepositorioPlaneaciones,
    RepositorioZonas,
)
from planeacion.domain.modelo import (
    Carro,
    Parametros,
    ReglasBalanceo,
    ZonaAgregada,
    clave_orden_carro,
    dia_de,
)
from planeacion.domain.modelo.parametros import CLAVE_KILOS_MAX_POR_UNIDAD
from planeacion.domain.servicios.balanceador import Balanceador

logger = logging.getLogger(__name__)


class CasoDeUsoGenerarPlaneacion:
    """Implementación del puerto de entrada ``GenerarPlaneacion``."""

    def __init__(
        self,
        pivote: GenerarPivotePorZona,
        carros: RepositorioCarros,
        zonas: RepositorioZonas,
        planeaciones: RepositorioPlaneaciones,
        carro_zonas: RepositorioCarroZonas,
        parametros: RepositorioParametros | None = None,
    ) -> None:
        self._pivote = pivote
        self._carros = carros
        self._zonas = zonas
        self._planeaciones = planeaciones
        self._carro_zonas = carro_zonas
        # Opcional: sin repositorio de parámetros se usan los defaults del
        # dominio, que es lo que necesitan las pruebas y una base sin migrar.
        self._parametros = parametros
        self._balanceador = Balanceador()

    def ejecutar(
        self,
        ruta_ecom: Path,
        fecha: date | None = None,
        reglas: ReglasBalanceo | None = None,
        usar_historico: bool = True,
        todas_las_fechas: bool = False,
    ) -> PlaneacionCompleta:
        # Los pesos del equilibrio y el techo de kilos salen de la tabla de
        # parámetros, salvo que quien llama imponga las reglas (los CLI de
        # medición lo hacen para poder comparar pesos distintos).
        configurados = self._configurados()
        reglas = reglas if reglas is not None else configurados.reglas_balanceo()
        pivote = self._pivote.ejecutar(
            ruta_ecom,
            fecha=fecha,
            todas_las_fechas=todas_las_fechas,
            kilos_max_por_unidad=configurados.numero(CLAVE_KILOS_MAX_POR_UNIDAD),
        )

        # El pivote entrega DTOs planos; se reconstruye la Zona de dominio (con su
        # regla de Chiquinquirá) casando el nombre contra la tabla de zonas.
        zonas_por_nombre = {zona.nombre: zona for zona in self._zonas.listar()}
        zonas_agregadas = [
            ZonaAgregada(
                zona=zonas_por_nombre[dto.zona],
                facturas=dto.facturas,
                clientes=dto.clientes,
                pesos=dto.pesos,
                kilos=dto.kilos,
            )
            for dto in pivote.zonas
        ]

        dia_semana = dia_de(pivote.fecha)
        # El repertorio depende del día: la misma zona la atiende un carro u otro
        # según sea lunes o sábado. Se resuelve el día ACÁ y al Balanceador se le
        # pasa solo el repertorio de ese día, así él sigue viendo un mapa plano
        # carro → zonas y no necesita saber que los días existen.
        repertorio = self._carro_zonas.obtener_por_dia(dia_semana)
        # La frecuencia de cada par (carro, zona) EN ESE DÍA: le sirve al balanceador
        # para desempatar entre carros elegibles a favor del que la operación real
        # viene usando. Se resuelve el día acá, igual que el repertorio.
        frecuencias = {
            (par.numero_carro, par.nombre_zona): veces
            for par, veces in self._carro_zonas.frecuencias().items()
            if par.dia_semana == dia_semana
        }
        if not any(repertorio.values()):
            logger.warning(
                "No hay repertorio configurado para %s: se balancea sin él "
                "(cualquier carro del municipio puede atender cualquier zona).",
                dia_semana,
            )

        # Sin histórico el balanceo arranca de cero (round-robin). Lo usa la
        # validación contra planeaciones manuales: si partiera de una planeación
        # guardada de ese mismo día, estaría midiéndose contra sí misma.
        previa = self._planeaciones.obtener_asignacion_previa(dia_semana) if usar_historico else None
        resultado = self._balanceador.balancear(
            zonas_agregadas=zonas_agregadas,
            carros_por_municipio=self._carros_por_municipio(),
            asignacion_previa=previa.zona_a_carro if previa else None,
            reglas=reglas,
            repertorio=repertorio,
            frecuencias=frecuencias,
        )
        return PlaneacionCompleta(
            fecha=pivote.fecha,
            dia_semana=dia_semana,
            resultado=resultado,
            total_facturas=pivote.total_facturas,
            total_clientes=pivote.total_clientes,
            total_pesos=pivote.total_pesos,
            total_kilos=pivote.total_kilos,
            no_resueltos=pivote.no_resueltos,
            pedidos_excluidos_por_fecha=pivote.pedidos_excluidos_por_fecha,
            facturas=pivote.facturas,
            fecha_previa=previa.fecha if previa and resultado.desde_historico else None,
            facturas_no_resueltas=pivote.facturas_no_resueltas,
            pesos_no_resueltos=pivote.pesos_no_resueltos,
            kilos_no_resueltos=pivote.kilos_no_resueltos,
            kilos_excluidos=pivote.kilos_excluidos,
            lineas_kilos_excluidos=pivote.lineas_kilos_excluidos,
        )

    def _configurados(self) -> Parametros:
        """Lo que haya en la base, con el catálogo del dominio como red."""
        if self._parametros is None:
            return Parametros()
        return Parametros(valores=self._parametros.obtener())

    def guardar(self, planeacion: PlaneacionCompleta) -> int:
        return self._planeaciones.guardar_planeacion(
            planeacion.fecha, planeacion.dia_semana, planeacion.asignaciones()
        )

    def _carros_por_municipio(self) -> dict[str, list[Carro]]:
        """Los carros activos agrupados por municipio, en orden estable por número
        (de ese orden sale la convención sur/norte de Chiquinquirá)."""
        agrupados: dict[str, list[Carro]] = {}
        for carro in self._carros.listar():
            if carro.activo and carro.municipio is not None:
                agrupados.setdefault(carro.municipio.nombre, []).append(carro)
        for carros in agrupados.values():
            carros.sort(key=lambda c: clave_orden_carro(c.numero))
        return agrupados
