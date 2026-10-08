"""Pruebas del emparejamiento .xlsm ↔ .xls de ECOM que usa `planeacion-validar --ecom`.

El emparejamiento es por **fecha de pedidos** y no por el nombre del .xlsm: esos
nombres traen erratas y nombran el día de entrega, no el de los pedidos. Acá se
fija ese criterio y, sobre todo, que un día sin su .xls quede reportado en vez de
medirse con otra entrada.
"""

from datetime import date
from pathlib import Path

import openpyxl

from planeacion.infraestructura.adaptadores.entrada.cli.validar import emparejar_por_fecha


def _xlsm_con_fecha(carpeta: Path, nombre: str, fecha: date | None) -> Path:
    """Un .xlsm mínimo con el bloque de ECOM en la columna S (como los reales)."""
    libro = openpyxl.Workbook()
    hoja = libro.active
    assert hoja is not None
    hoja.title = "PEDIDOS"
    # La tabla de trabajo manual de la izquierda, con su propio 'Fecha' trampa.
    izquierda = ["Fecha", "R. Social", "CODIGO"] + [None] * 15
    hoja.append(izquierda + ["Tipo", "Pedido", "Est", "Fecha"])
    if fecha is not None:
        hoja.append([date(2020, 1, 1)] + [None] * 17 + ["PEDIDO", "6004679", None, fecha.isoformat()])
    ruta = carpeta / nombre
    libro.save(ruta)
    return ruta


def test_empareja_cada_dia_con_el_xls_de_su_fecha_de_pedidos(tmp_path: Path) -> None:
    lunes = _xlsm_con_fecha(tmp_path, "DEL 05-10 PARA EL 07-10.xlsm", date(2026, 10, 5))
    martes = _xlsm_con_fecha(tmp_path, "DEL 06-10 PARA EL 08-10.xlsm", date(2026, 10, 6))
    ecom_lunes = tmp_path / "infpedidos202610050.27276300.xls"
    ecom_martes = tmp_path / "infpedidos202610060.57523300.xls"

    parejas, sin_pareja = emparejar_por_fecha([lunes, martes], [ecom_martes, ecom_lunes])

    assert parejas == {lunes: ecom_lunes, martes: ecom_martes}
    assert sin_pareja == []


def test_el_dia_sin_su_xls_queda_sin_pareja_y_no_se_mide(tmp_path: Path) -> None:
    """Medirlo con la entrada de otro día sería peor que no medirlo."""
    con_ecom = _xlsm_con_fecha(tmp_path, "DEL 06-10 PARA EL 08-10.xlsm", date(2026, 10, 6))
    sin_ecom = _xlsm_con_fecha(tmp_path, "DEL 18 PARA EL 21 SEPTIEMBRE.xlsm", date(2026, 9, 18))
    ecom = tmp_path / "infpedidos202610060.57523300.xls"

    parejas, sin_pareja = emparejar_por_fecha([con_ecom, sin_ecom], [ecom])

    assert parejas == {con_ecom: ecom}
    assert sin_pareja == [sin_ecom]


def test_el_nombre_del_xlsm_no_decide_nada(tmp_path: Path) -> None:
    """El nombre dice "DEL 29-09" pero los pedidos son del 30: manda el bloque."""
    archivo = _xlsm_con_fecha(tmp_path, "DEL 29-09 PARA EL 01-10.xlsm", date(2026, 9, 30))
    ecom_30 = tmp_path / "infpedidos202609300.95702100.xls"

    parejas, _ = emparejar_por_fecha([archivo], [tmp_path / "infpedidos202609290.88467100.xls", ecom_30])

    assert parejas == {archivo: ecom_30}


def test_un_xlsm_sin_fecha_en_el_bloque_no_se_empareja(tmp_path: Path) -> None:
    archivo = _xlsm_con_fecha(tmp_path, "DEL 01-10 PARA EL 03-10.xlsm", None)

    parejas, sin_pareja = emparejar_por_fecha([archivo], [tmp_path / "infpedidos202610010.15308000.xls"])

    assert parejas == {}
    assert sin_pareja == [archivo]


def test_un_xls_con_nombre_que_no_trae_fecha_se_ignora(tmp_path: Path) -> None:
    archivo = _xlsm_con_fecha(tmp_path, "DEL 06-10 PARA EL 08-10.xlsm", date(2026, 10, 6))

    parejas, sin_pareja = emparejar_por_fecha([archivo], [tmp_path / "pedidos_del_martes.xls"])

    assert parejas == {}
    assert sin_pareja == [archivo]
