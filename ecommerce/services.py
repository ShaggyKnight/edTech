"""Servicios del flujo de compra online.

Dos pasos, no uno (a diferencia del POS):
  1. `iniciar_pedido` crea un ReciboVenta pendiente con canal='online',
     construye las líneas y pide al gateway una URL de redirect. No toca
     stock todavía — solo valida que exista disponibilidad razonable.
  2. `confirmar_pedido` se ejecuta cuando el cliente vuelve de la pasarela;
     pregunta al gateway por el resultado y lo aplica con
     `aplicar_resultado_pago` (el mismo camino que webhooks y la
     confirmacion manual de transferencias): si fue pagado bloquea stock
     con select_for_update, valida otra vez, descuenta y audita — todo
     dentro de @transaction.atomic. Si falta stock tras el pago, el recibo
     queda 'fallido' con `pago_recibido_en` (por devolver) y se avisa al
     dueño.

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
from django.utils import timezone

from bodega.models import MovimientoStock, StockTienda, Tienda
from catalogo.models import Producto, ProductoVariante
from ecommerce.emails import (
    enviar_boleta,
    notificar_dueno_nueva_orden,
    notificar_dueno_pago_por_devolver,
)
from ecommerce.gateways import (
    OnlinePaymentInit,
    get_gateway,
    get_gateway_default,
    get_online_gateway,  # alias retrocompat de get_gateway_default
)
from pos.models import ReciboVenta, ReciboVentaDetalle
from pos.payments import (
    ESTADO_CANCELADO, ESTADO_FALLIDO, ESTADO_PAGADO,
    PaymentGatewayError, PaymentResult,
)

log = logging.getLogger(__name__)


class TiendaOnlineNoConfigurada(Exception):
    """settings.ECOMMERCE_TIENDA_ID no apunta a una tienda activa."""


class StockInsuficienteOnline(Exception):
    def __init__(self, descripcion: str, disponible: int, solicitado: int,
                 *, tipo: str = '', item_id: int = 0):
        self.descripcion = descripcion
        self.disponible = disponible
        self.solicitado = solicitado
        # Sprint 2 · 2.1: tipo + item_id permiten marcar la linea exacta
        # en el carrito al redireccionar despues del fallo.
        self.tipo = tipo
        self.item_id = item_id
        super().__init__(
            f'Stock insuficiente para {descripcion}: disponible={disponible}, solicitado={solicitado}'
        )


class ProductoNoDisponibleOnline(Exception):
    """Un item del carrito ya no se vende online (producto o variante
    desactivados despues de agregarlo, o un POST armado a mano)."""

    def __init__(self, descripcion: str, *, tipo: str = '', item_id: int = 0):
        self.descripcion = descripcion
        self.tipo = tipo
        self.item_id = item_id
        super().__init__(f'{descripcion} ya no está disponible')


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
    gateway_nombre: str = '',
) -> tuple[ReciboVenta, OnlinePaymentInit]:
    """Crea un recibo 'online' pendiente y devuelve la URL para redirect."""
    items = list(items)
    if not items:
        raise ValueError('El carrito está vacío')

    tienda = get_tienda_online()

    # Solo se venden productos activos (el mismo criterio del catalogo y
    # la ficha). Un carrito viejo o un POST directo no se saltan eso.
    vendibles = keys_vendibles_online(items)
    for item in items:
        if (item.tipo, item.item_id) not in vendibles:
            raise ProductoNoDisponibleOnline(
                _descripcion(item), tipo=item.tipo, item_id=item.item_id,
            )

    # Validación best-effort (no bloqueante) contra stock actual.
    stock_disponible = _stock_snapshot(tienda, items)
    subtotal_bruto = Decimal('0')
    descuento_total = Decimal('0')
    for item in items:
        disp = stock_disponible.get((item.tipo, item.item_id), 0)
        if disp < item.cantidad:
            raise StockInsuficienteOnline(
                _descripcion(item), disp, item.cantidad,
                tipo=item.tipo, item_id=item.item_id,
            )
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
        cliente_telefono=cliente_telefono,
        cliente_direccion=cliente_direccion,
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
    # gateway_nombre: el cliente eligio uno especifico en el checkout
    # (multi-gateway). Si no se pasa, usamos el default.
    if gateway_nombre:
        try:
            gateway = get_gateway(gateway_nombre)
        except KeyError as exc:
            raise PaymentGatewayError(f'Gateway invalido: {exc}') from exc
    else:
        # get_online_gateway es alias de get_gateway_default; preservado
        # como mock-point estable para los tests.
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
    """Cierra el flujo: consulta al gateway y aplica el resultado.

    Busca el recibo por `payment_reference` (token del gateway). No vuelve
    a llamar al gateway si el pedido ya esta resuelto: pagado, o fallido
    con el pago recibido (sin stock, por devolver). Un fallido/cancelado
    SIN pago si se vuelve a consultar: en Mercado Pago el cliente puede
    pagar con otro medio despues de un rechazo.
    """
    try:
        recibo = ReciboVenta.objects.get(
            canal=ReciboVenta.CANAL_ONLINE,
            payment_reference=token,
        )
    except ReciboVenta.DoesNotExist as exc:
        raise PedidoNoEncontrado(f'No hay pedido con token {token!r}') from exc

    if recibo.estado == ReciboVenta.ESTADO_PAGADO or recibo.pago_recibido_en:
        return recibo  # idempotencia: ya estaba resuelto

    try:
        gateway = _gateway_del_recibo(recibo)
    except PaymentGatewayError as exc:
        # Pasarela desactivada (p. ej. se sacaron sus credenciales del
        # .env): no se puede consultar. El pedido queda como esta — el
        # webhook o un reintento lo resuelven cuando vuelva a operar.
        log.warning('No se pudo consultar el pago del recibo #%s: %s', recibo.pk, exc)
        return recibo
    result = gateway.confirmar_pago(token)
    return aplicar_resultado_pago(recibo, result)


def _gateway_del_recibo(recibo: ReciboVenta):
    """Gateway que proceso el pago del recibo; si no esta registrado,
    el default. get_online_gateway() = alias estable (los tests lo
    mockean)."""
    if recibo.payment_provider:
        try:
            return get_gateway(recibo.payment_provider)
        except KeyError:
            pass
    return get_online_gateway()


# Avisos que dispara una transicion (se mandan despues de guardar).
_AVISO_PAGADO = 'pagado'
_AVISO_POR_DEVOLVER = 'por_devolver'


def aplicar_resultado_pago(recibo: ReciboVenta, result: PaymentResult) -> ReciboVenta:
    """Aplica el resultado de la pasarela al recibo. Es EL punto de
    transicion a pagado: lo usan el retorno, los webhooks y la
    confirmacion manual de transferencias.

    Reglas:
      - PENDIENTE (Khipu conciliando, Mercado Pago en revision, red
        caida): no cambia nada; el webhook o un reintento lo resuelven.
      - FALLIDO / CANCELADO: solo cierran un pedido pendiente.
      - PAGADO: pasa a pagado si hay stock; si no, queda fallido "por
        devolver" (con pago_recibido_en). Tambien aplica sobre un
        fallido/cancelado sin pago: tras un rechazo el cliente puede
        pagar con otro medio, y la plata recibida manda.
      - Pagado es terminal, igual que un fallido con pago ya recibido
        (los avisos duplicados no repiten nada).

    Los correos (boleta al cliente, aviso al dueño) salen despues de
    guardar y una sola vez por transicion: webhooks repetidos y recargas
    del retorno no los duplican.
    """
    recibo, aviso = _aplicar_resultado(recibo, result)
    if aviso == _AVISO_PAGADO:
        _avisar(recibo, enviar_boleta, notificar_dueno_nueva_orden)
    elif aviso == _AVISO_POR_DEVOLVER:
        _avisar(recibo, notificar_dueno_pago_por_devolver)
    return recibo


def _acepta_resultado(recibo: ReciboVenta, result: PaymentResult) -> bool:
    """True si el resultado cambia el recibo (reglas en aplicar_resultado_pago)."""
    if result.estado == ESTADO_PAGADO:
        return (recibo.estado != ReciboVenta.ESTADO_PAGADO
                and recibo.pago_recibido_en is None)
    if result.estado in (ESTADO_FALLIDO, ESTADO_CANCELADO):
        return recibo.estado == ReciboVenta.ESTADO_PENDIENTE
    return False


def _avisar(recibo: ReciboVenta, *envios) -> None:
    """Correos post-pago. Best-effort: un correo caido no deshace el pago."""
    for enviar in envios:
        try:
            enviar(recibo)
        except Exception:  # noqa: BLE001
            log.exception('Fallo %s del recibo #%s', enviar.__name__, recibo.pk)


@transaction.atomic
def _aplicar_resultado(recibo: ReciboVenta, result: PaymentResult):
    """Transicion bajo lock. Devuelve (recibo, aviso a mandar o None)."""
    # Re-lee bajo lock por si se está confirmando dos veces en paralelo
    # (el retorno y el webhook suelen llegar casi juntos).
    recibo = ReciboVenta.objects.select_for_update().get(pk=recibo.pk)
    if not _acepta_resultado(recibo, result):
        return recibo, None

    estado_anterior = recibo.estado
    recibo.payment_provider = result.provider or recibo.payment_provider

    if result.estado != ESTADO_PAGADO:
        recibo.estado = (
            ReciboVenta.ESTADO_CANCELADO
            if result.estado == ESTADO_CANCELADO
            else ReciboVenta.ESTADO_FALLIDO
        )
        recibo.save(update_fields=['estado', 'payment_provider', 'modificado'])
        return recibo, None

    if estado_anterior != ReciboVenta.ESTADO_PENDIENTE:
        log.warning(
            'Recibo #%s: pago aprobado despues de quedar %s (reintento del '
            'cliente) — se cierra como pagado si hay stock.',
            recibo.pk, estado_anterior,
        )
    recibo.pago_recibido_en = timezone.now()
    campos = ['estado', 'payment_provider', 'pago_recibido_en', 'modificado']

    # Stock. Este es el punto crítico: el cliente ya pagó, hay que cumplir.
    items = list(recibo.detalles.all())
    filas = _lock_stock(recibo.tienda, items)
    for det in items:
        fila = filas[_stock_key(det)]
        if fila.cantidad < det.cantidad:
            # Stock se evaporó entre iniciar_pedido y confirmar_pedido.
            # Fallido "por devolver" (pago_recibido_en queda puesto) y
            # aviso al dueño — NO cobramos dos veces.
            recibo.estado = ReciboVenta.ESTADO_FALLIDO
            recibo.save(update_fields=campos)
            log.error(
                'Pago online recibido pero stock insuficiente post-pago. '
                'Recibo #%s, requiere refund manual.', recibo.pk,
            )
            return recibo, _AVISO_POR_DEVOLVER

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
    recibo.save(update_fields=campos)

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

    # WhatsApp automatico al cliente (funcionalidad activable — no-op
    # mientras FEATURE_WHATSAPP_AUTO este apagada). Va aca porque este
    # es EL punto de transicion a pagado: cubre retorno Y webhook.
    from ecommerce.whatsapp import notificar_pedido_confirmado
    notificar_pedido_confirmado(recibo)

    return recibo, _AVISO_PAGADO


def variantes_vendibles_online():
    """Variantes que se pueden comprar online: activa, de un producto
    activo y con variantes (mismo criterio que la ficha y las etiquetas)."""
    return ProductoVariante.objects.filter(
        activa=True, producto__activo=True, producto__tiene_variantes=True,
    )


def productos_vendibles_online():
    """Productos sin variantes que se pueden comprar online."""
    return Producto.objects.filter(activo=True, tiene_variantes=False)


def keys_vendibles_online(items) -> set[tuple[str, int]]:
    """De los items dados, las claves (tipo, id) que siguen a la venta."""
    variante_ids = [i.item_id for i in items if i.tipo == 'v']
    producto_ids = [i.item_id for i in items if i.tipo == 'p']
    keys: set[tuple[str, int]] = set()
    if variante_ids:
        keys.update(('v', pk) for pk in variantes_vendibles_online()
                    .filter(pk__in=variante_ids).values_list('pk', flat=True))
    if producto_ids:
        keys.update(('p', pk) for pk in productos_vendibles_online()
                    .filter(pk__in=producto_ids).values_list('pk', flat=True))
    return keys


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
