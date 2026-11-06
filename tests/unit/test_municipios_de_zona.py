"""Pruebas de la corrección de municipio por nombre y por evidencia.

Lo que se fija acá es el criterio: cuándo una zona en `OTROS` es en realidad de un
municipio y cuándo es una viajera de verdad que tiene que quedarse como está. La
diferencia la decide **quién la repartió en los archivos**, no el nombre.
"""

from collections import Counter

from planeacion.domain.modelo import MUNICIPIO_OTROS, Cliente, Municipio, Zona
from planeacion.infraestructura.adaptadores.entrada.cli.municipios_de_zona import (
    normalizar_ciudad,
    proponer_por_el_nombre,
    proponer_por_evidencia,
    proponer_por_la_ciudad_del_cliente,
)

_OTROS = Municipio(nombre="OTROS")
_TUNJA = Municipio(nombre="TUNJA")

# Rutas 14-22 son de Tunja; 8-13 son las viajeras, que balancean en OTROS.
_POOL = {"11": "OTROS", "12": "OTROS", "14": "TUNJA", "15": "TUNJA", "21": "TUNJA"}


def _zona(nombre: str, municipio: Municipio = _OTROS, activa: bool = True) -> Zona:
    return Zona(nombre=nombre, municipio=municipio, activa=activa)


class TestPorElNombre:
    def test_propone_el_municipio_que_el_nombre_ya_decia(self) -> None:
        """La fila quedó en OTROS porque el parseo viejo no leía el paréntesis
        corrido; el nombre nunca dejó de decirlo."""
        zonas = [_zona("Y (TUNJA): RUTA OCCIDENTE"), _zona("PARAISO (TUNJA)")]

        propuestas = proponer_por_el_nombre(zonas)

        assert [(p.nombre, p.municipio_propuesto) for p in propuestas] == [
            ("PARAISO (TUNJA)", "TUNJA"),
            ("Y (TUNJA): RUTA OCCIDENTE", "TUNJA"),
        ]
        assert all(p.por_el_nombre for p in propuestas)

    def test_una_zona_ya_coherente_no_se_propone(self) -> None:
        assert proponer_por_el_nombre([_zona("(TUNJA): NIEVES", _TUNJA)]) == []

    def test_una_viajera_sin_prefijo_no_entra_por_esta_via(self) -> None:
        """Su nombre no dice nada: si corresponde, la decide la evidencia."""
        assert proponer_por_el_nombre([_zona("VENTAQUEMADA - VUELTA AL MUNDO")]) == []


class TestPorLaEvidencia:
    def test_la_reparten_siempre_rutas_de_tunja_entonces_es_de_tunja(self) -> None:
        zonas = [_zona("VENTAQUEMADA - VUELTA AL MUNDO")]
        observaciones = {"VENTAQUEMADA - VUELTA AL MUNDO": Counter({"14": 10, "15": 3})}

        propuestas = proponer_por_evidencia(
            zonas, _POOL, observaciones, Counter({"VENTAQUEMADA - VUELTA AL MUNDO": 143})
        )

        assert len(propuestas) == 1
        propuesta = propuestas[0]
        assert (propuesta.municipio_propuesto, propuesta.clientes) == ("TUNJA", 143)
        assert propuesta.asignaciones == 13
        assert propuesta.unanime
        assert not propuesta.por_el_nombre

    def test_una_viajera_de_verdad_se_queda_en_otros(self) -> None:
        """La reparten rutas viajeras: el pool mayoritario es OTROS y no se toca."""
        zonas = [_zona("RUTA MUZO")]
        observaciones = {"RUTA MUZO": Counter({"12": 16})}

        assert proponer_por_evidencia(zonas, _POOL, observaciones, Counter()) == []

    def test_cuando_no_es_unanime_se_propone_el_mayoritario_y_queda_marcado(self) -> None:
        """Una sola aparición de otra ruta no manda, pero tiene que verse."""
        zonas = [_zona("VIAJERA 1 (RAMIRIQUI)")]
        observaciones = {"VIAJERA 1 (RAMIRIQUI)": Counter({"14": 5, "15": 2, "11": 1})}
        clientes = Counter({"VIAJERA 1 (RAMIRIQUI)": 49})

        propuesta = proponer_por_evidencia(zonas, _POOL, observaciones, clientes)[0]

        assert propuesta.municipio_propuesto == "TUNJA"
        assert not propuesta.unanime
        assert "NO unánime" in propuesta.evidencia

    def test_una_zona_sin_ninguna_observacion_no_se_propone(self) -> None:
        """Sin evidencia no se adivina: queda como está y se ve en el reporte de
        zonas sin carro."""
        assert proponer_por_evidencia([_zona("PH MARTHA")], _POOL, {}, Counter()) == []

    def test_una_zona_que_no_esta_en_otros_no_se_toca(self) -> None:
        zonas = [_zona("(TUNJA): NIEVES", _TUNJA)]
        observaciones = {"(TUNJA): NIEVES": Counter({"14": 5})}

        assert proponer_por_evidencia(zonas, _POOL, observaciones, Counter()) == []

    def test_raquira_queda_excluida_por_decision_del_negocio(self) -> None:
        """Es la zona viajera de manual y el caso está documentado: cambiarla
        escondería el ejemplo."""
        zonas = [_zona("RAQUIRA")]
        observaciones = {"RAQUIRA": Counter({"21": 6})}

        assert proponer_por_evidencia(zonas, _POOL, observaciones, Counter()) == []

    def test_el_orden_pone_primero_lo_mejor_sostenido(self) -> None:
        zonas = [_zona("POCA EVIDENCIA"), _zona("MUCHA EVIDENCIA")]
        observaciones = {
            "POCA EVIDENCIA": Counter({"14": 3}),
            "MUCHA EVIDENCIA": Counter({"14": 9}),
        }
        clientes = Counter({"POCA EVIDENCIA": 10, "MUCHA EVIDENCIA": 10})

        propuestas = proponer_por_evidencia(zonas, _POOL, observaciones, clientes)

        assert [p.nombre for p in propuestas] == ["MUCHA EVIDENCIA", "POCA EVIDENCIA"]


class TestPisoDeEvidencia:
    """Un solo cliente visto una o dos veces no alcanza para mover de pool."""

    def test_un_cliente_con_dos_observaciones_se_queda_en_otros(self) -> None:
        zonas = [_zona("COMFABOY")]
        observaciones = {"COMFABOY": Counter({"14": 1, "15": 1})}

        propuestas = proponer_por_evidencia(zonas, _POOL, observaciones, Counter({"COMFABOY": 1}))

        assert propuestas == []

    def test_pocos_clientes_pero_evidencia_sostenida_si_cambia(self) -> None:
        """VDA FORAQUIRA JENESANO: 5 clientes y 5 asignaciones alcanzan."""
        zonas = [_zona("VDA FORAQUIRA JENESANO")]
        observaciones = {"VDA FORAQUIRA JENESANO": Counter({"14": 3, "15": 1, "12": 1})}
        clientes = Counter({"VDA FORAQUIRA JENESANO": 5})

        propuestas = proponer_por_evidencia(zonas, _POOL, observaciones, clientes)

        assert [p.municipio_propuesto for p in propuestas] == ["TUNJA"]

    def test_muchos_clientes_con_dos_observaciones_tampoco_alcanza(self) -> None:
        """Los dos pisos se exigen juntos: la zona puede ser grande y el dato de
        quién la reparte seguir siendo anecdótico."""
        zonas = [_zona("ZONA GRANDE POCO VISTA")]
        observaciones = {"ZONA GRANDE POCO VISTA": Counter({"14": 2})}
        clientes = Counter({"ZONA GRANDE POCO VISTA": 80})

        assert proponer_por_evidencia(zonas, _POOL, observaciones, clientes) == []


class TestIdempotencia:
    def test_un_nombre_que_no_dice_municipio_no_devuelve_la_zona_a_otros(self) -> None:
        """Una zona clasificada por evidencia (VENTAQUEMADA, sin prefijo, en TUNJA)
        no se puede revertir por el nombre: correr el comando dos veces dejaría la
        base como estaba."""
        zonas = [_zona("VENTAQUEMADA - VUELTA AL MUNDO", _TUNJA)]

        assert proponer_por_el_nombre(zonas) == []

    def test_un_nombre_que_si_dice_municipio_sigue_corrigiendo(self) -> None:
        assert len(proponer_por_el_nombre([_zona("PARAISO (TUNJA)", _OTROS)])) == 1


class TestNormalizarCiudad:
    def test_quita_el_codigo_dane_que_pega_ecom(self) -> None:
        assert normalizar_ciudad("15001 - TUNJA") == "TUNJA"
        assert normalizar_ciudad("68077 - BARBOSA") == "BARBOSA"

    def test_no_corta_un_nombre_con_guion_de_verdad(self) -> None:
        """`BARBOSA - PUENTE NACIONAL` es el nombre completo, no un prefijo."""
        assert normalizar_ciudad("BARBOSA - PUENTE NACIONAL") == "BARBOSA - PUENTE NACIONAL"

    def test_normaliza_espacios_y_mayusculas(self) -> None:
        assert normalizar_ciudad("  tunja ") == "TUNJA"

    def test_vacia_o_nula(self) -> None:
        assert normalizar_ciudad("") == ""


class TestMunicipioPorLaCiudadDelCliente:
    """El municipio de una zona de UN cliente se decide por su dirección.

    La evidencia por rutas no la alcanza (exige 2 clientes y 3 asignaciones), y
    tampoco habría que usarla: mide **quién la repartió**, que puede ser
    circunstancial. A COMFABOY la llevó una ruta de Tunja y su cliente está en
    Moniquirá, que en esta base la atiende Barbosa con 294 clientes. El camión
    cambia; la puerta no.

    El pool de cada ciudad sale de la **propia base**: no hay una tabla de
    municipios de Boyacá en el código, y no hace falta.
    """

    _TUNJA = Municipio(nombre="TUNJA")
    _BARBOSA = Municipio(nombre="BARBOSA")
    _OTROS = Municipio(nombre=MUNICIPIO_OTROS)

    def _zonas_y_clientes(self) -> tuple[list[Zona], list[Cliente]]:
        normal = Zona(nombre="(BARBOSA): MONIQUIRA", municipio=self._BARBOSA)
        especial = Zona(nombre="COMFABOY", municipio=self._OTROS, especial=True)
        clientes = [
            Cliente(codigo=f"m{i}", razon_social="x", zona=normal, ciudad="MONIQUIRA") for i in range(8)
        ]
        clientes.append(Cliente(codigo="c1", razon_social="Comfaboy", zona=especial, ciudad="MONIQUIRA"))
        return [normal, especial], clientes

    def test_propone_el_pool_que_atiende_la_ciudad_del_cliente(self) -> None:
        zonas, clientes = self._zonas_y_clientes()

        propuestas = proponer_por_la_ciudad_del_cliente(zonas, clientes, {"COMFABOY"})

        assert [(p.nombre, p.municipio_propuesto) for p in propuestas] == [("COMFABOY", "BARBOSA")]
        assert propuestas[0].ciudad_del_cliente == "MONIQUIRA"

    def test_la_zona_especial_no_vota_su_propia_ciudad(self) -> None:
        """Si se contara a sí misma, una zona en OTROS se confirmaría en OTROS."""
        especial = Zona(nombre="COMFABOY", municipio=self._OTROS, especial=True)
        clientes = [
            Cliente(codigo=f"c{i}", razon_social="x", zona=especial, ciudad="MONIQUIRA") for i in range(9)
        ]

        propuestas = proponer_por_la_ciudad_del_cliente([especial], clientes, {"COMFABOY"})

        assert propuestas[0].municipio_propuesto is None
        assert "ninguna zona normal atiende MONIQUIRA" in propuestas[0].motivo

    def test_una_ciudad_de_verdad_aparte_se_queda_en_otros(self) -> None:
        """El cliente de MEDELLIN está en Medellín, a 400 km: no hay pool que lo
        atienda y moverlo sería mentir."""
        normal = Zona(nombre="(TUNJA): NIEVES", municipio=self._TUNJA)
        especial = Zona(nombre="MEDELLIN", municipio=self._OTROS, especial=True)
        clientes = [Cliente(codigo=f"t{i}", razon_social="x", zona=normal, ciudad="TUNJA") for i in range(9)]
        clientes.append(Cliente(codigo="m1", razon_social="x", zona=especial, ciudad="MEDELLIN"))

        propuestas = proponer_por_la_ciudad_del_cliente([normal, especial], clientes, {"MEDELLIN"})

        assert propuestas[0].municipio_propuesto is None

    def test_una_ciudad_con_poquitos_clientes_no_decide(self) -> None:
        """Con menos de MINIMO_CLIENTES_DE_LA_CIUDAD la ciudad no tiene geografía
        establecida en la base: mejor dejarla quieta que moverla por un dato."""
        normal = Zona(nombre="(TUNJA): NIEVES", municipio=self._TUNJA)
        especial = Zona(nombre="IMPACTA", municipio=self._OTROS, especial=True)
        clientes = [
            Cliente(codigo="t1", razon_social="x", zona=normal, ciudad="SORACA"),
            Cliente(codigo="i1", razon_social="x", zona=especial, ciudad="SORACA"),
        ]

        propuestas = proponer_por_la_ciudad_del_cliente([normal, especial], clientes, {"IMPACTA"})

        assert propuestas[0].municipio_propuesto is None

    def test_la_que_ya_esta_en_el_pool_correcto_no_se_propone(self) -> None:
        normal = Zona(nombre="(TUNJA): NIEVES", municipio=self._TUNJA)
        especial = Zona(nombre="(TUNJA): PIZZA NOSTRA", municipio=self._TUNJA, especial=True)
        clientes = [Cliente(codigo=f"t{i}", razon_social="x", zona=normal, ciudad="TUNJA") for i in range(9)]
        clientes.append(Cliente(codigo="p1", razon_social="x", zona=especial, ciudad="TUNJA"))

        propuestas = proponer_por_la_ciudad_del_cliente(
            [normal, especial], clientes, {"(TUNJA): PIZZA NOSTRA"}
        )

        assert propuestas[0].municipio_propuesto is None
        assert "ya está en TUNJA" in propuestas[0].motivo

    def test_el_codigo_dane_no_parte_la_ciudad_en_dos(self) -> None:
        """`15001 - TUNJA` y `TUNJA` son la misma ciudad y tienen que sumar juntas."""
        normal = Zona(nombre="(TUNJA): NIEVES", municipio=self._TUNJA)
        especial = Zona(nombre="DISTRIROSAS", municipio=self._OTROS, especial=True)
        clientes = [
            Cliente(codigo=f"t{i}", razon_social="x", zona=normal, ciudad="15001 - TUNJA") for i in range(5)
        ]
        clientes.append(Cliente(codigo="d1", razon_social="x", zona=especial, ciudad="TUNJA"))

        propuestas = proponer_por_la_ciudad_del_cliente([normal, especial], clientes, {"DISTRIROSAS"})

        assert propuestas[0].municipio_propuesto == "TUNJA"
