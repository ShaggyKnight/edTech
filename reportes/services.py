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
    # Mejora dashboard: filtro de canal aplicado (None = ambos canales).
    canal: Optional[str] = None
    # Mejora dashboard: snapshot del período inmediatamente anterior, para
    # poder mostrar "↑ +18% vs período anterior" bajo cada KPI. None si no
    # se pidió calcularlo (incluir_anterior=False).
    anterior: Optional[dict] = None


def _recibos_pagados_qs(tienda=None, desde=None, hasta=None, canal=None):
    qs = ReciboVenta.objects.filter(estado=ReciboVenta.ESTADO_PAGADO)
    if tienda is not None:
        qs = qs.filter(tienda=tienda)
    if canal is not None:
        # Filtro de canal a nivel de queryset — afecta a TODAS las
        # funciones que parten de `_recibos_pagados_qs` (ventas por canal,
        # ventas por periodo, top productos, total). El saldo de caja y
        # el valor de inventario NO se filtran por canal porque son
        # conceptualmente trans-canal.
        qs = qs.filter(canal=canal)
    if desde is not None:
        qs = qs.filter(creado__gte=desde)
    if hasta is not None:
        # `__lte` (no `__lt`) para que un recibo creado en el mismo instante
        # que `hasta` (caso común cuando el dashboard llama con timezone.now())
        # entre en la ventana. En Windows la resolución de tiempo es más
        # gruesa y `__lt` causa flakes en CI.
        qs = qs.filter(creado__lte=hasta)
    return qs


def variacion_pct(actual: Decimal, anterior: Decimal) -> Optional[int]:
    """Devuelve el % de variación de `actual` vs `anterior` como int redondeado.

    - Si anterior == 0 y actual == 0 → None (no hay info comparable).
    - Si anterior == 0 y actual > 0 → None también; el caller debe mostrar
      "Nuevo" en vez de un porcentaje (división por cero da infinito).
    - Si anterior > 0 → ((actual - anterior) / anterior) * 100, redondeado.

    Ejemplo:
        >>> variacion_pct(Decimal('120'), Decimal('100'))
        20
        >>> variacion_pct(Decimal('80'), Decimal('100'))
        -20
        >>> variacion_pct(Decimal('0'), Decimal('0')) is None
        True
    """
    if anterior is None or anterior == 0:
        return None
    delta = (Decimal(actual) - Decimal(anterior)) / Decimal(anterior) * Decimal('100')
    return int(delta.quantize(Decimal('1')))


def ventas_por_canal(
    *,
    tienda: Optional[Tienda] = None,
    desde=None,
    hasta=None,
    canal: Optional[str] = None,
) -> dict:
    """Entrega {canal: {'n_ventas': int, 'total': Decimal}} para la ventana.

    Siempre incluye las llaves 'presencial' y 'online' (aunque valgan 0) para
    que los templates no tengan que manejar dict incompleto.

    `canal` parametro: si se pasa, los resultados solo cuentan ventas de
    ese canal (los demas quedan en 0).
    """
    qs = _recibos_pagados_qs(tienda, desde, hasta, canal)
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
    canal: Optional[str] = None,
) -> list[dict]:
    """Serie diaria [{fecha, n_ventas, total}, ...] ordenada ascendente."""
    qs = _recibos_pagados_qs(tienda, desde, hasta, canal)
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
    canal: Optional[str] = None,
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
    if canal is not None:
        qs = qs.filter(recibo__canal=canal)
    if desde is not None:
        qs = qs.filter(recibo__creado__gte=desde)
    if hasta is not None:
        # `__lte` por consistencia con `_recibos_pagados_qs`: un recibo
        # creado en el instante exacto de `hasta` debe contar para el ranking.
        qs = qs.filter(recibo__creado__lte=hasta)

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
    canal: Optional[str] = None,
    incluir_anterior: bool = False,
    top_limite: int = 5,
) -> ResumenNegocio:
    """Snapshot integral para el dashboard del administrador.

    Parametros nuevos:
      - `canal`: si se pasa ('presencial' / 'online'), las KPIs de venta
        solo cuentan ese canal. La caja y el inventario quedan completos
        (son conceptos trans-canal).
      - `incluir_anterior`: si True, calcula el mismo snapshot para el
        periodo inmediatamente anterior (ventana de mismo ancho, terminando
        en `desde`) y lo adjunta como `resumen.anterior` (dict con las
        metricas clave). Permite mostrar la variacion vs periodo previo
        en el dashboard.
    """
    if desde is None or hasta is None:
        d, h = ventana_por_defecto()
        desde = desde or d
        hasta = hasta or h

    por_canal = ventas_por_canal(tienda=tienda, desde=desde, hasta=hasta, canal=canal)
    total = sum((c['total'] for c in por_canal.values()), Decimal('0'))
    n_ventas = sum(c['n_ventas'] for c in por_canal.values())
    caja = resumen_caja(tienda=tienda, desde=desde, hasta=hasta)
    inventario = valor_inventario(tienda=tienda)
    top = top_productos(
        tienda=tienda, desde=desde, hasta=hasta, canal=canal, limite=top_limite,
    )

    anterior_dict: Optional[dict] = None
    if incluir_anterior:
        ancho = hasta - desde
        desde_prev = desde - ancho
        hasta_prev = desde
        por_canal_prev = ventas_por_canal(
            tienda=tienda, desde=desde_prev, hasta=hasta_prev, canal=canal,
        )
        total_prev = sum((c['total'] for c in por_canal_prev.values()), Decimal('0'))
        n_prev = sum(c['n_ventas'] for c in por_canal_prev.values())
        caja_prev = resumen_caja(tienda=tienda, desde=desde_prev, hasta=hasta_prev)
        anterior_dict = {
            'desde': desde_prev,
            'hasta': hasta_prev,
            'total_ventas': total_prev,
            'n_ventas': n_prev,
            'presencial_total': por_canal_prev[ReciboVenta.CANAL_PRESENCIAL]['total'],
            'online_total': por_canal_prev[ReciboVenta.CANAL_ONLINE]['total'],
            'caja_saldo': caja_prev.saldo,
            # Variaciones pre-calculadas para que el template no haga math.
            'var_total': variacion_pct(total, total_prev),
            'var_presencial': variacion_pct(
                por_canal[ReciboVenta.CANAL_PRESENCIAL]['total'],
                por_canal_prev[ReciboVenta.CANAL_PRESENCIAL]['total'],
            ),
            'var_online': variacion_pct(
                por_canal[ReciboVenta.CANAL_ONLINE]['total'],
                por_canal_prev[ReciboVenta.CANAL_ONLINE]['total'],
            ),
            'var_caja': variacion_pct(caja.saldo, caja_prev.saldo),
        }

    return ResumenNegocio(
        desde=desde,
        hasta=hasta,
        ventas_por_canal=por_canal,
        total_ventas=total,
        n_ventas=n_ventas,
        caja=caja,
        valor_inventario=inventario,
        top_productos=top,
        canal=canal,
        anterior=anterior_dict,
    )
