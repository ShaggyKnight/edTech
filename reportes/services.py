"""Agregaciones de negocio sobre las ventas pagadas.

Todas las funciones operan solo sobre `ReciboVenta` en estado `pagado` para
que los reportes reflejen dinero real cobrado, no intenciones de compra.

- `ventas_por_canal`: dict {canal: {n_ventas, total}} en la ventana.
- `ventas_por_periodo`: lista ordenada por día con {fecha, n_ventas, total}.
- `top_productos`: ranking por cantidad vendida (con fallback a descripcion).
- `resumen_negocio`: snapshot compacto para el dashboard — combina ventas,
  caja y valor de inventario en una sola estructura.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Optional

from django.db.models import (
    Count,
    DecimalField,
    F,
    Q,
    Sum,
    Value,
)
from django.db.models.functions import Coalesce, TruncDate
from django.utils import timezone

from bodega.models import Tienda
from contabilidad.services import ResumenCaja, resumen_caja, valor_inventario
from pos.models import ReciboVenta, ReciboVentaDetalle


@dataclass
class ResumenNegocio:
    desde: datetime
    hasta: datetime
    ventas_por_canal: dict
    total_ventas: Decimal
    n_ventas: int
    caja: ResumenCaja
    valor_inventario: Decimal
    top_productos: list = field(default_factory=list)


def _recibos_pagados_qs(tienda=None, desde=None, hasta=None):
    qs = ReciboVenta.objects.filter(estado=ReciboVenta.ESTADO_PAGADO)
    if tienda is not None:
        qs = qs.filter(tienda=tienda)
    if desde is not None:
        qs = qs.filter(creado__gte=desde)
    if hasta is not None:
        qs = qs.filter(creado__lt=hasta)
    return qs


def ventas_por_canal(
    *,
    tienda: Optional[Tienda] = None,
    desde=None,
    hasta=None,
) -> dict:
    """Entrega {canal: {'n_ventas': int, 'total': Decimal}} para la ventana.

    Siempre incluye las llaves 'presencial' y 'online' (aunque valgan 0) para
    que los templates no tengan que manejar dict incompleto.
    """
    qs = _recibos_pagados_qs(tienda, desde, hasta)
    base = {
        ReciboVenta.CANAL_PRESENCIAL: {'n_ventas': 0, 'total': Decimal('0')},
        ReciboVenta.CANAL_ONLINE: {'n_ventas': 0, 'total': Decimal('0')},
    }
    filas = (
        qs.values('canal')
        .annotate(
            n_ventas=Count('id'),
            total=Coalesce(Sum('total'), Value(Decimal('0')), output_field=DecimalField()),
        )
        .order_by('canal')
    )
    for row in filas:
        base[row['canal']] = {'n_ventas': row['n_ventas'], 'total': row['total']}
    return base


def ventas_por_periodo(
    *,
    tienda: Optional[Tienda] = None,
    desde=None,
    hasta=None,
) -> list[dict]:
    """Serie diaria [{fecha, n_ventas, total}, ...] ordenada ascendente."""
    qs = _recibos_pagados_qs(tienda, desde, hasta)
    filas = (
        qs.annotate(dia=TruncDate('creado'))
        .values('dia')
        .annotate(
            n_ventas=Count('id'),
            total=Coalesce(Sum('total'), Value(Decimal('0')), output_field=DecimalField()),
        )
        .order_by('dia')
    )
    return [
        {'fecha': row['dia'], 'n_ventas': row['n_ventas'], 'total': row['total']}
        for row in filas
    ]


def top_productos(
    *,
    tienda: Optional[Tienda] = None,
    desde=None,
    hasta=None,
    limite: int = 10,
) -> list[dict]:
    """Ranking de productos por unidades vendidas en recibos pagados.

    Agrupa por descripción (snapshot tomado al momento de la venta) porque es
    el identificador estable: variante y producto pueden coexistir en la misma
    línea y queremos un solo ranking fusionado.
    """
    qs = ReciboVentaDetalle.objects.filter(
        recibo__estado=ReciboVenta.ESTADO_PAGADO
    )
    if tienda is not None:
        qs = qs.filter(recibo__tienda=tienda)
    if desde is not None:
        qs = qs.filter(recibo__creado__gte=desde)
    if hasta is not None:
        qs = qs.filter(recibo__creado__lt=hasta)

    filas = (
        qs.values('descripcion')
        .annotate(
            unidades=Coalesce(Sum('cantidad'), Value(0)),
            ingreso=Coalesce(
                Sum(F('cantidad') * F('precio_unitario') - F('descuento')),
                Value(Decimal('0')),
                output_field=DecimalField(),
            ),
        )
        .order_by('-unidades', '-ingreso')[:limite]
    )
    return [
        {
            'descripcion': row['descripcion'],
            'unidades': row['unidades'],
            'ingreso': row['ingreso'],
        }
        for row in filas
    ]


def ventana_por_defecto(dias: int = 30) -> tuple[datetime, datetime]:
    """Ventana estándar para el dashboard: últimos N días hasta ahora."""
    hasta = timezone.now()
    desde = hasta - timedelta(days=dias)
    return desde, hasta


def resumen_negocio(
    *,
    tienda: Optional[Tienda] = None,
    desde=None,
    hasta=None,
    top_limite: int = 5,
) -> ResumenNegocio:
    """Snapshot integral para el dashboard del administrador."""
    if desde is None or hasta is None:
        d, h = ventana_por_defecto()
        desde = desde or d
        hasta = hasta or h

    por_canal = ventas_por_canal(tienda=tienda, desde=desde, hasta=hasta)
    total = sum((c['total'] for c in por_canal.values()), Decimal('0'))
    n_ventas = sum(c['n_ventas'] for c in por_canal.values())
    caja = resumen_caja(tienda=tienda, desde=desde, hasta=hasta)
    inventario = valor_inventario(tienda=tienda)
    top = top_productos(tienda=tienda, desde=desde, hasta=hasta, limite=top_limite)

    return ResumenNegocio(
        desde=desde,
        hasta=hasta,
        ventas_por_canal=por_canal,
        total_ventas=total,
        n_ventas=n_ventas,
        caja=caja,
        valor_inventario=inventario,
        top_productos=top,
    )
