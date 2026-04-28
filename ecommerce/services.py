"""Servicios del flujo de compra online.

Dos pasos, no uno (a diferencia del POS):
  1. `iniciar_pedido` crea un ReciboVenta pendiente con canal='online',
     construye las líneas y pide al gateway una URL de redirect. No toca
     stock todavía — solo valida que exista disponibilidad razonable.
  2. `confirmar_pedido` se ejecuta cuando el cliente vuelve de la pasarela;
     pregunta al gateway por el resultado, y si fue pagado bloquea stock
     con select_for_update, valida otra vez, descuenta y audita — todo
     dentro de @transaction.atomic. Si falta stock tras el pago, el recibo
     queda en estado 'fallido' con mensaje para refund manual.

La tienda que surte el canal online se configura con
`settings.ECOMMERCE_TIENDA_ID`; si no está o apunta a una tienda inactiva
se levanta `TiendaOnlineNoConfigurada`.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable, Optional

from django.conf import settings
from django.db import transaction
from django.db.models import F

from bodega.models import MovimientoStock, StockTienda, Tienda
from catalogo.models import Producto, ProductoVariante
from ecommerce.payments import OnlinePaymentInit, get_online_gateway
from pos.models import ReciboVenta, ReciboVentaDetalle
from pos.payments import ESTADO_PAGADO, PaymentGatewayError, PaymentResult

log = logging.getLogger(__name__)


class TiendaOnlineNoConfigurada(Exception):
    """settings.ECOMMERCE_TIENDA_ID no apunta a una tienda activa."""


class StockInsuficienteOnline(Exception):
    def __init__(self, descripcion: str, disponible: int, solicitado: int):
        self.descripcion = descripcion
        self.disponible = disponible
        self.solicitado = solicitado
        super().__init__(
            f'Stock insuficiente para {descripcion}: disponible={disponible}, solicitado={solicitado}'
        )


class PedidoNoEncontrado(Exception):
    """No se encontró el ReciboVenta con el idempotency key dado."""


@dataclass
class ItemPedido:
    tipo: str  # 'v' | 'p'
    item_id: int
    cantidad: int
    precio_unitario: Decimal
    descuento_total: Decimal


def get_tienda_online() -> Tienda:
    tid = getattr(settings, 'ECOMMERCE_TIENDA_ID', None)
    if not tid:
        raise TiendaOnlineNoConfigurada(
            'settings.ECOMMERCE_TIENDA_ID no configurado; la tienda online no puede operar.'
        )
    try:
        return Tienda.objects.get(pk=tid, activa=True)
    except Tienda.DoesNotExist as exc:
        raise TiendaOnlineNoConfigurada(
            f'ECOMMERCE_TIENDA_ID={tid} no existe o está inactiva.'
        ) from exc


@transaction.atomic
def iniciar_pedido(
    *,
    items: Iterable[ItemPedido],
    cliente_nombre: str,
    cliente_email: str,
    cliente_rut: str = '',
    cliente_telefono: str = '',
    cliente_direccion: str = '',
    cliente_usuario=None,
    return_url: str,
) -> tuple[ReciboVenta, OnlinePaymentInit]:
    """Crea un recibo 'online' pendiente y devuelve la URL para redirect."""
    items = list(items)
    if not items:
        raise ValueError('El carrito está vacío')

    tienda = get_tienda_online()

    # Validación best-effort (no bloqueante) contra stock actual.
    stock_disponible = _stock_snapshot(tienda, items)
    subtotal_bruto = Decimal('0')
    descuento_total = Decimal('0')
    for item in items:
        disp = stock_disponible.get((item.tipo, item.item_id), 0)
        if disp < item.cantidad:
            raise StockInsuficienteOnline(_descripcion(item), disp, item.cantidad)
        subtotal_bruto += item.precio_unitario * item.cantidad
        descuento_total += item.descuento_total
    total_neto = subtotal_bruto - descuento_total

    recibo = ReciboVenta.objects.create(
        canal=ReciboVenta.CANAL_ONLINE,
        tienda=tienda,
        vendedor=None,
        cliente_nombre=cliente_nombre,
        cliente_email=cliente_email,
        cliente_rut=cliente_rut,
        cliente_usuario=cliente_usuario,
        subtotal=subtotal_bruto,
        descuento=descuento_total,
        total=total_neto,
        estado=ReciboVenta.ESTADO_PENDIENTE,
        payment_idempotency_key=str(uuid.uuid4()),
    )

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

    # Iniciamos el pago fuera del lock de stock: la pasarela no debería
    # reservar stock, y queremos liberar la transacción rápido.
    gateway = get_online_gateway()
    try:
        init = gateway.iniciar_pago(recibo, return_url=return_url)
    except PaymentGatewayError as exc:
        log.warning('Fallo al iniciar pago online: %s', exc)
        raise

    recibo.payment_provider = init.provider
    recibo.payment_reference = init.token
    recibo.save(update_fields=['payment_provider', 'payment_reference', 'modificado'])

    return recibo, init


def confirmar_pedido(*, token: str) -> ReciboVenta:
    """Cierra el flujo: consulta al gateway y, si fue pagado, descuenta stock.

    Busca el recibo por `payment_reference` (token del gateway). Idempotente:
    si el recibo ya está en estado terminal lo devuelve sin volver a llamar
    al gateway.
    """
    try:
        recibo = ReciboVenta.objects.get(
            canal=ReciboVenta.CANAL_ONLINE,
            payment_reference=token,
        )
    except ReciboVenta.DoesNotExist as exc:
        raise PedidoNoEncontrado(f'No hay pedido con token {token!r}') from exc

    if recibo.estado in (
        ReciboVenta.ESTADO_PAGADO,
        ReciboVenta.ESTADO_FALLIDO,
        ReciboVenta.ESTADO_CANCELADO,
    ):
        return recibo  # idempotencia: ya estaba resuelto

    gateway = get_online_gateway()
    result = gateway.confirmar_pago(token)
    return _aplicar_resultado(recibo, result)


@transaction.atomic
def _aplicar_resultado(recibo: ReciboVenta, result: PaymentResult) -> ReciboVenta:
    """Aplica el PaymentResult al recibo; descuenta stock solo si pagó."""
    # Re-lee bajo lock por si se está confirmando dos veces en paralelo.
    recibo = ReciboVenta.objects.select_for_update().get(pk=recibo.pk)
    if recibo.estado != ReciboVenta.ESTADO_PENDIENTE:
        return recibo

    recibo.payment_provider = result.provider or recibo.payment_provider

    if result.estado != ESTADO_PAGADO:
        recibo.estado = (
            ReciboVenta.ESTADO_CANCELADO
            if result.estado == 'cancelado'
            else ReciboVenta.ESTADO_FALLIDO
        )
        recibo.save(update_fields=['estado', 'payment_provider', 'modificado'])
        return recibo

    # Stock. Este es el punto crítico: el cliente ya pagó, hay que cumplir.
    items = list(recibo.detalles.all())
    filas = _lock_stock(recibo.tienda, items)
    for det in items:
        fila = filas[_stock_key(det)]
        if fila.cantidad < det.cantidad:
            # Stock se evaporó entre iniciar_pedido y confirmar_pedido.
            # Marcamos fallido para refund manual — NO cobramos dos veces.
            recibo.estado = ReciboVenta.ESTADO_FALLIDO
            recibo.save(update_fields=['estado', 'payment_provider', 'modificado'])
            log.error(
                'Pago online recibido pero stock insuficiente post-pago. '
                'Recibo #%s, requiere refund manual.', recibo.pk,
            )
            return recibo

    for det in items:
        fila = filas[_stock_key(det)]
        StockTienda.objects.filter(pk=fila.pk).update(cantidad=F('cantidad') - det.cantidad)
        mov_kwargs = {
            'tienda': recibo.tienda,
            'tipo': MovimientoStock.SALIDA,
            'cantidad': det.cantidad,
            'referencia': f'Recibo online #{recibo.pk}',
        }
        if det.variante_id:
            mov_kwargs['variante_id'] = det.variante_id
        else:
            mov_kwargs['producto_id'] = det.producto_id
        MovimientoStock.objects.create(**mov_kwargs)

    recibo.estado = ReciboVenta.ESTADO_PAGADO
    recibo.save(update_fields=['estado', 'payment_provider', 'modificado'])

    # Asiento contable de ingreso (idempotente).
    # Import local: evita dependencias circulares con contabilidad en el arranque.
    from contabilidad.services import registrar_ingreso_venta
    registrar_ingreso_venta(recibo)

    # Emisión de DTE (boleta electrónica al SII). Idempotente y best-effort:
    # si el emisor falla, la venta queda pagada y el dueño puede reemitir
    # manualmente más tarde — preferimos no perder la venta por un fallo del
    # servicio externo.
    from pos.dte import emitir_si_corresponde
    emitir_si_corresponde(recibo)

    return recibo


# --- helpers internos ---


def _stock_key(item) -> tuple[str, int]:
    if isinstance(item, ItemPedido):
        return (item.tipo, item.item_id)
    # ReciboVentaDetalle
    if item.variante_id:
        return ('v', item.variante_id)
    return ('p', item.producto_id)


def _stock_snapshot(tienda: Tienda, items: Iterable[ItemPedido]) -> dict:
    variante_ids = [i.item_id for i in items if i.tipo == 'v']
    producto_ids = [i.item_id for i in items if i.tipo == 'p']
    out: dict[tuple[str, int], int] = {}
    if variante_ids:
        for fila in StockTienda.objects.filter(tienda=tienda, variante_id__in=variante_ids):
            out[('v', fila.variante_id)] = fila.cantidad
    if producto_ids:
        for fila in StockTienda.objects.filter(tienda=tienda, producto_id__in=producto_ids):
            out[('p', fila.producto_id)] = fila.cantidad
    return out


def _lock_stock(tienda: Tienda, detalles) -> dict:
    variante_ids = [d.variante_id for d in detalles if d.variante_id]
    producto_ids = [d.producto_id for d in detalles if d.producto_id]
    filas: dict[tuple[str, int], StockTienda] = {}
    if variante_ids:
        for f in (
            StockTienda.objects.select_for_update()
            .filter(tienda=tienda, variante_id__in=variante_ids)
        ):
            filas[('v', f.variante_id)] = f
    if producto_ids:
        for f in (
            StockTienda.objects.select_for_update()
            .filter(tienda=tienda, producto_id__in=producto_ids)
        ):
            filas[('p', f.producto_id)] = f
    # Si no existe la fila, crearla a 0 para poder bloquear.
    for d in detalles:
        if _stock_key(d) in filas:
            continue
        kwargs = {'tienda': tienda, 'cantidad': 0}
        if d.variante_id:
            kwargs['variante_id'] = d.variante_id
        else:
            kwargs['producto_id'] = d.producto_id
        f, _ = StockTienda.objects.select_for_update().get_or_create(**kwargs)
        filas[_stock_key(d)] = f
    return filas


def _descripcion(item: ItemPedido) -> str:
    if item.tipo == 'v':
        v = ProductoVariante.objects.select_related('producto').get(pk=item.item_id)
        valores = ', '.join(str(va) for va in v.valores.all())
        return f'{v.producto.nombre} [{v.sku}]' + (f' ({valores})' if valores else '')
    p = Producto.objects.get(pk=item.item_id)
    return p.nombre
