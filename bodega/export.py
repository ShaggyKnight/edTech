"""Exportacion de listados del backoffice a CSV.

Formato pensado para que Blanca lo abra con doble click en Excel (Chile):

  - UTF-8 con BOM: sin el BOM, Excel asume la codificacion del sistema
    (cp1252) y los acentos / la n con tilde salen rotos.
  - Separador ';': en Excel es-CL la coma es el separador DECIMAL, asi
    que si usaramos ',' como separador de columnas Excel meteria toda
    la fila en una sola celda. Con ';' cada columna cae en su lugar.

Uso:
    return csv_response('productos', columnas, filas)
    # -> descarga "productos_2026-07-03.csv"
"""
from __future__ import annotations

import csv
from datetime import date
from typing import Iterable, Sequence

from django.http import HttpResponse

BOM = '﻿'


def _celda(valor) -> str:
    """Normaliza un valor a texto para el CSV.

    None -> '' ; los booleanos a Si/No (mas legible que True/False para
    quien abre el Excel).
    """
    if valor is None:
        return ''
    if valor is True:
        return 'Si'
    if valor is False:
        return 'No'
    return str(valor)


def csv_response(nombre_base: str, columnas: Sequence[str],
                 filas: Iterable[Sequence]) -> HttpResponse:
    """Devuelve un HttpResponse con un CSV descargable.

    `nombre_base`: sin extension ni fecha (se agregan aca).
    `columnas`: encabezados.
    `filas`: iterable de secuencias con los valores de cada fila.
    """
    nombre_archivo = f'{nombre_base}_{date.today():%Y-%m-%d}.csv'
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="{nombre_archivo}"'
    # BOM UTF-8 para que Excel detecte la codificacion.
    response.write(BOM)
    writer = csv.writer(response, delimiter=';', lineterminator='\r\n')
    writer.writerow(list(columnas))
    for fila in filas:
        writer.writerow([_celda(v) for v in fila])
    return response
