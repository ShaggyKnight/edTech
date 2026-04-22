"""Servicios de contabilidad.

Principios:
- Las ventas pagadas (`ReciboVenta` en estado `pagado`) se reflejan como
  `MovimientoCaja.ENTRADA` con FK al recibo. La operación es idempotente:
  dos llamadas seguidas producen un solo asiento.
- Los egresos manuales (arriendo, sueldos, compra a proveedor) se registran
  con `registrar_salida` desde el admin.
- La valorización de activos (`valor_inventario`) es `sum(stock ×
  precio_costo)` por tienda, al momento de la consulta; no se persiste.
- El saldo de caja se computa como suma de entradas − suma de salidas en
  la ventana indicada.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from django.db import transaction
from django.db.models import F, Q, Sum, Value
from django.db.models.functions import Coalesce

from bodega.models import StockTienda, Tienda
from contabilidad.models import MovimientoCaja
from pos.models import ReciboVenta


@dataclass
class ResumenCaja:
    entradas: Decimal
    salidas: Decimal

    @property
    def saldo(self) -> Decimal:
        return self.entradas - self.salidas


@transaction.atomic
def registrar_ingreso_venta(recibo: ReciboVenta, usuario=None) -> Optional[MovimientoCaja]:
    """Crea un MovimientoCaja.ENTRADA por un recibo pagado si no existe aún.

    Devuelve el MovimientoCaja creado o `None` si el recibo no está pagado
    o ya había un asiento previo.
    """
    if recibo.estado != ReciboVenta.ESTADO_PAGADO:
        return None

    # Lock sobre recibo para evitar doble-asiento en concurrencia.
    ReciboVenta.objects.select_for_update().filter(pk=recibo.pk).exists()
    if MovimientoCaja.objects.filter(
        recibo_venta=recibo, tipo=MovimientoCaja.ENTRADA
    ).exists():
        return None

    concepto = f'Venta #{recibo.pk} ({recibo.get_canal_display()})'
    return MovimientoCaja.objects.create(
        tienda=recibo.tienda,
        tipo=MovimientoCaja.ENTRADA,
        monto=recibo.total,
        concepto=concepto,
        recibo_venta=recibo,
        usuario=usuario if getattr(usuario, 'is_authenticated', False) else None,
    )


def registrar_salida(
    *,
    tienda: Tienda,
    monto: Decimal,
    concepto: str,
    usuario=None,
) -> MovimientoCaja:
    """Registra un egreso manual (compra, sueldo, arriendo)."""
    if monto <= 0:
        raise ValueError('El monto de la salida debe ser mayor a 0')
    if not concepto.strip():
        raise ValueError('El concepto es obligatorio')
    return MovimientoCaja.objects.create(
        tienda=tienda,
        tipo=MovimientoCaja.SALIDA,
        monto=monto,
        concepto=concepto.strip(),
        usuario=usuario if getattr(usuario, 'is_authenticated', False) else None,
    )


def resumen_caja(
    *,
    tienda: Optional[Tienda] = None,
    desde=None,
    hasta=None,
) -> ResumenCaja:
    """Resumen de entradas y salidas en la ventana indicada."""
    qs = MovimientoCaja.objects.all()
    if tienda is not None:
        qs = qs.filter(tienda=tienda)
    if desde is not None:
        qs = qs.filter(fecha__gte=desde)
    if hasta is not None:
        qs = qs.filter(fecha__lt=hasta)

    agregados = qs.aggregate(
        entradas=Coalesce(
            Sum('monto', filter=Q(tipo=MovimientoCaja.ENTRADA)),
            Value(Decimal('0')),
        ),
        salidas=Coalesce(
            Sum('monto', filter=Q(tipo=MovimientoCaja.SALIDA)),
            Value(Decimal('0')),
        ),
    )
    return ResumenCaja(entradas=agregados['entradas'], salidas=agregados['salidas'])


def valor_inventario(tienda: Optional[Tienda] = None) -> Decimal:
    """Suma `stock.cantidad × precio_costo` para valorizar el activo.

    Si una variante tiene `precio_override`, el costo sigue siendo el del
    producto padre (el override refiere al precio de venta, no al costo).
    """
    qs = StockTienda.objects.all()
    if tienda is not None:
        qs = qs.filter(tienda=tienda)

    total = Decimal('0')
    # Stock de variantes → costo desde producto padre.
    variantes_valor = (
        qs.filter(variante__isnull=False)
        .annotate(valor=F('cantidad') * F('variante__producto__precio_costo'))
        .aggregate(total=Coalesce(Sum('valor'), Value(Decimal('0'))))
    )['total']
    total += variantes_valor

    # Stock de productos directos.
    directos_valor = (
        qs.filter(producto__isnull=False)
        .annotate(valor=F('cantidad') * F('producto__precio_costo'))
        .aggregate(total=Coalesce(Sum('valor'), Value(Decimal('0'))))
    )['total']
    total += directos_valor
    return total
