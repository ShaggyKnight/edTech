"""Servicios transaccionales del POS presencial.

- `procesar_venta`: crea el recibo pendiente, cobra vía gateway, descuenta
  stock atómicamente y registra MovimientoStock. Si el cobro falla, se
  levanta la excepción correspondiente y la transacción se revierte.

- `get_active_tienda`: obtiene la sucursal activa desde la sesión; si hay
  una sola tienda activa la autoselecciona.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable

from django.db import transaction
from django.db.models import F

from bodega.models import MovimientoStock, StockTienda, Tienda
from catalogo.models import Producto, ProductoVariante
from pos.models import ReciboVenta, ReciboVentaDetalle
from pos.payments import (
    ESTADO_PAGADO,
    PaymentGatewayError,
    PaymentResult,
    get_gateway,
)


class StockInsuficiente(Exception):
    def __init__(self, item, disponible: int, solicitado: int):
        self.item = item
        self.disponible = disponible
        self.solicitado = solicitado
        super().__init__(
            f'Stock insuficiente para {item}: disponible={disponible}, solicitado={solicitado}'
        )


class CobroFallido(Exception):
    def __init__(self, result: PaymentResult):
        self.result = result
        super().__init__(result.detalle or f'Cobro fallido ({result.estado})')


@dataclass
class ItemVenta:
    """Representa una línea pendiente antes de crear el recibo."""
    tipo: str  # 'v' | 'p'
    item_id: int
    cantidad: int
    precio_unitario: Decimal
    descuento_total: Decimal


SESSION_TIENDA_KEY = 'tienda_activa_id'


def get_active_tienda(request) -> Tienda | None:
    """Resuelve la sucursal activa para este cajero.

    Primero intenta leerla de la sesión; si no hay, y solo existe una tienda
    activa, la auto-selecciona y la persiste en sesión. Devuelve `None` si no
    hay tiendas creadas todavía.
    """
    tienda_id = request.session.get(SESSION_TIENDA_KEY)
    if tienda_id:
        try:
            return Tienda.objects.get(pk=tienda_id, activa=True)
        except Tienda.DoesNotExist:
            request.session.pop(SESSION_TIENDA_KEY, None)

    activas = list(Tienda.objects.filter(activa=True)[:2])
    if len(activas) == 1:
        request.session[SESSION_TIENDA_KEY] = activas[0].pk
        request.session.modified = True
        return activas[0]
    return None


@transaction.atomic
def procesar_venta(
    *,
    tienda: Tienda,
    vendedor,
    items: Iterable[ItemVenta],
    cliente_nombre: str = '',
    cliente_email: str = '',
    cliente_rut: str = '',
    dte_tipo: int | None = None,
) -> ReciboVenta:
    """Crea el recibo, cobra y descuenta stock en una sola transacción.

    Si falta stock o el pago falla, se levanta `StockInsuficiente` o
    `CobroFallido` y la transacción se revierte completa.
    """
    items = list(items)
    if not items:
        raise ValueError('No hay items para procesar')

    # 1. Lock de las filas de stock afectadas (select_for_update).
    filas_stock = _lock_stock_filas(tienda, items)

    # 2. Validación de stock disponible.
    subtotal_bruto = Decimal('0')
    descuento_total = Decimal('0')
    for item in items:
        fila = filas_stock[_stock_key(item)]
        if fila.cantidad < item.cantidad:
            raise StockInsuficiente(fila, fila.cantidad, item.cantidad)
        subtotal_bruto += item.precio_unitario * item.cantidad
        descuento_total += item.descuento_total
    total_neto = subtotal_bruto - descuento_total

    # 3. Crea el recibo en estado pendiente con idempotency key.
    recibo = ReciboVenta.objects.create(
        canal=ReciboVenta.CANAL_PRESENCIAL,
        tienda=tienda,
        vendedor=vendedor if getattr(vendedor, 'is_authenticated', False) else None,
        cliente_nombre=cliente_nombre,
        cliente_email=cliente_email,
        cliente_rut=cliente_rut,
        subtotal=subtotal_bruto,
        descuento=descuento_total,
        total=total_neto,
        estado=ReciboVenta.ESTADO_PENDIENTE,
        payment_idempotency_key=str(uuid.uuid4()),
        dte_tipo=dte_tipo,
    )

    # 4. Detalles del recibo (snapshot de descripciones).
    detalles = []
    for item in items:
        kwargs = {
            'recibo': recibo,
            'descripcion': _descripcion(item),
            'cantidad': item.cantidad,
            'precio_unitario': item.precio_unitario,
            'descuento': item.descuento_total,
        }
        if item.tipo == 'v':
            kwargs['variante_id'] = item.item_id
        else:
            kwargs['producto_id'] = item.item_id
        detalles.append(ReciboVentaDetalle(**kwargs))
    ReciboVentaDetalle.objects.bulk_create(detalles)

    # 5. Cobro vía gateway. Bloquea hasta resolver (sync para Mock, polling para TUU).
    try:
        gateway = get_gateway()
        result = gateway.cobrar(recibo)
    except PaymentGatewayError as exc:
        raise CobroFallido(PaymentResult(estado='fallido', provider='', detalle=str(exc)))

    recibo.payment_provider = result.provider
    recibo.payment_reference = result.reference

    if result.estado != ESTADO_PAGADO:
        recibo.estado = ReciboVenta.ESTADO_FALLIDO
        recibo.save(update_fields=['payment_provider', 'payment_reference', 'estado', 'modificado'])
        raise CobroFallido(result)

    recibo.estado = ReciboVenta.ESTADO_PAGADO
    recibo.save(update_fields=['payment_provider', 'payment_reference', 'estado', 'modificado'])

    # 6. Descontar stock y auditar movimientos.
    for item in items:
        fila = filas_stock[_stock_key(item)]
        StockTienda.objects.filter(pk=fila.pk).update(cantidad=F('cantidad') - item.cantidad)
        mov_kwargs = {
            'tienda': tienda,
            'tipo': MovimientoStock.SALIDA,
            'cantidad': item.cantidad,
            'referencia': f'Recibo #{recibo.pk}',
            'usuario': vendedor if getattr(vendedor, 'is_authenticated', False) else None,
        }
        if item.tipo == 'v':
            mov_kwargs['variante_id'] = item.item_id
        else:
            mov_kwargs['producto_id'] = item.item_id
        MovimientoStock.objects.create(**mov_kwargs)

    return recibo


# --- helpers internos ---


def _stock_key(item: ItemVenta) -> tuple[str, int]:
    return (item.tipo, item.item_id)


def _lock_stock_filas(tienda: Tienda, items: Iterable[ItemVenta]) -> dict:
    """Hace SELECT ... FOR UPDATE de todas las filas de stock afectadas."""
    variante_ids = [i.item_id for i in items if i.tipo == 'v']
    producto_ids = [i.item_id for i in items if i.tipo == 'p']

    filas = {}
    if variante_ids:
        for fila in (
            StockTienda.objects
            .select_for_update()
            .filter(tienda=tienda, variante_id__in=variante_ids)
        ):
            filas[('v', fila.variante_id)] = fila
    if producto_ids:
        for fila in (
            StockTienda.objects
            .select_for_update()
            .filter(tienda=tienda, producto_id__in=producto_ids)
        ):
            filas[('p', fila.producto_id)] = fila

    # Si falta una fila (nunca se registró stock), la creamos a 0 para poder bloquearla
    # y dejar que la validación posterior falle con StockInsuficiente.
    for item in items:
        if _stock_key(item) not in filas:
            kwargs = {'tienda': tienda, 'cantidad': 0}
            if item.tipo == 'v':
                kwargs['variante_id'] = item.item_id
            else:
                kwargs['producto_id'] = item.item_id
            fila, _ = StockTienda.objects.select_for_update().get_or_create(**kwargs)
            filas[_stock_key(item)] = fila
    return filas


def _descripcion(item: ItemVenta) -> str:
    if item.tipo == 'v':
        v = ProductoVariante.objects.select_related('producto').get(pk=item.item_id)
        valores = ', '.join(str(va) for va in v.valores.all())
        return f'{v.producto.nombre} [{v.sku}]' + (f' ({valores})' if valores else '')
    p = Producto.objects.get(pk=item.item_id)
    return p.nombre
