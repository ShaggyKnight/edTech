"""Tests del flujo iniciar_pedido + confirmar_pedido del ecommerce."""

from decimal import Decimal
from unittest import mock

from django.test import TestCase, override_settings

from bodega.models import MovimientoStock, StockTienda, Tienda
from catalogo.models import Familia, Producto
from ecommerce.gateways import OnlinePaymentInit
from ecommerce.services import (
    ItemPedido,
    StockInsuficienteOnline,
    TiendaOnlineNoConfigurada,
    confirmar_pedido,
    iniciar_pedido,
)
from pos.models import ReciboVenta
from pos.payments import ESTADO_CANCELADO, ESTADO_FALLIDO, ESTADO_PAGADO, PaymentResult


class _StubGateway:
    provider = 'stub'

    def __init__(self, result_estado=ESTADO_PAGADO):
        self._result_estado = result_estado
        self.iniciar_calls = 0
        self.confirmar_calls = 0

    def iniciar_pago(self, recibo, return_url):
        self.iniciar_calls += 1
        return OnlinePaymentInit(
            redirect_url=f'https://mock.pay/{recibo.pk}',
            token=f'TOK-{recibo.pk}',
            provider=self.provider,
        )

    def confirmar_pago(self, token):
        self.confirmar_calls += 1
        return PaymentResult(
            estado=self._result_estado,
            provider=self.provider,
            reference=token,
            detalle='stub',
        )


@override_settings(ECOMMERCE_PAYMENT_GATEWAY='mock')
class IniciarPedidoTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.familia = Familia.objects.create(nombre='Perfumes')
        cls.tienda = Tienda.objects.create(nombre_organizacion='Tienda Online', activa=True)
        cls.producto = Producto.objects.create(
            familia=cls.familia,
            nombre='Perfume 30ml',
            precio_base=Decimal('10000'),
            tiene_variantes=False,
        )
        StockTienda.objects.create(tienda=cls.tienda, producto=cls.producto, cantidad=5)

    def _item(self, cantidad, precio='10000'):
        return ItemPedido(
            tipo='p', item_id=self.producto.pk, cantidad=cantidad,
            precio_unitario=Decimal(precio), descuento_total=Decimal('0'),
        )

    def test_iniciar_pedido_sin_tienda_configurada_falla(self):
        with self.settings(ECOMMERCE_TIENDA_ID=None):
            with self.assertRaises(TiendaOnlineNoConfigurada):
                iniciar_pedido(
                    items=[self._item(1)],
                    cliente_nombre='X', cliente_email='x@x.cl',
                    return_url='http://t/',
                )

    def test_iniciar_pedido_sin_items_falla(self):
        with self.settings(ECOMMERCE_TIENDA_ID=self.tienda.pk):
            with self.assertRaises(ValueError):
                iniciar_pedido(
                    items=[],
                    cliente_nombre='X', cliente_email='x@x.cl',
                    return_url='http://t/',
                )

    def test_iniciar_pedido_stock_insuficiente_bloquea(self):
        stub = _StubGateway()
        with self.settings(ECOMMERCE_TIENDA_ID=self.tienda.pk), \
             mock.patch('ecommerce.services.get_online_gateway', return_value=stub):
            with self.assertRaises(StockInsuficienteOnline):
                iniciar_pedido(
                    items=[self._item(99)],
                    cliente_nombre='X', cliente_email='x@x.cl',
                    return_url='http://t/',
                )

        # No se creó recibo porque la excepción se levanta antes.
        self.assertFalse(ReciboVenta.objects.exists())
        self.assertEqual(stub.iniciar_calls, 0)

    def test_iniciar_pedido_exitoso_crea_recibo_pendiente_y_pide_url_al_gateway(self):
        stub = _StubGateway()
        with self.settings(ECOMMERCE_TIENDA_ID=self.tienda.pk), \
             mock.patch('ecommerce.services.get_online_gateway', return_value=stub):
            recibo, init = iniciar_pedido(
                items=[self._item(2)],
                cliente_nombre='Juana', cliente_email='j@x.cl', cliente_rut='11.111.111-1',
                return_url='http://t/retorno',
            )

        self.assertEqual(recibo.canal, ReciboVenta.CANAL_ONLINE)
        self.assertEqual(recibo.estado, ReciboVenta.ESTADO_PENDIENTE)
        self.assertEqual(recibo.total, Decimal('20000'))
        self.assertEqual(recibo.payment_provider, 'stub')
        self.assertEqual(recibo.payment_reference, f'TOK-{recibo.pk}')
        self.assertEqual(recibo.detalles.count(), 1)

        # Stock todavía NO se descuenta en iniciar_pedido.
        stock = StockTienda.objects.get(tienda=self.tienda, producto=self.producto)
        self.assertEqual(stock.cantidad, 5)

        self.assertEqual(init.token, f'TOK-{recibo.pk}')
        self.assertEqual(stub.iniciar_calls, 1)


@override_settings(ECOMMERCE_PAYMENT_GATEWAY='mock')
class ConfirmarPedidoTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.familia = Familia.objects.create(nombre='Perfumes')
        cls.tienda = Tienda.objects.create(nombre_organizacion='Tienda Online', activa=True)
        cls.producto = Producto.objects.create(
            familia=cls.familia,
            nombre='Perfume 30ml',
            precio_base=Decimal('10000'),
            tiene_variantes=False,
        )
        StockTienda.objects.create(tienda=cls.tienda, producto=cls.producto, cantidad=5)

    def _crear_pedido_pendiente(self, stub):
        with self.settings(ECOMMERCE_TIENDA_ID=self.tienda.pk), \
             mock.patch('ecommerce.services.get_online_gateway', return_value=stub):
            item = ItemPedido(
                tipo='p', item_id=self.producto.pk, cantidad=2,
                precio_unitario=Decimal('10000'), descuento_total=Decimal('0'),
            )
            recibo, init = iniciar_pedido(
                items=[item],
                cliente_nombre='Juana', cliente_email='j@x.cl',
                return_url='http://t/',
            )
        return recibo, init

    def test_confirmar_pedido_pagado_descuenta_stock_y_audita(self):
        stub = _StubGateway(result_estado=ESTADO_PAGADO)
        recibo, init = self._crear_pedido_pendiente(stub)

        with mock.patch('ecommerce.services.get_online_gateway', return_value=stub):
            resultado = confirmar_pedido(token=init.token)

        resultado.refresh_from_db()
        self.assertEqual(resultado.estado, ReciboVenta.ESTADO_PAGADO)
        self.assertEqual(stub.confirmar_calls, 1)

        stock = StockTienda.objects.get(tienda=self.tienda, producto=self.producto)
        self.assertEqual(stock.cantidad, 3)

        movs = MovimientoStock.objects.filter(tipo=MovimientoStock.SALIDA)
        self.assertEqual(movs.count(), 1)
        self.assertEqual(movs[0].cantidad, 2)

    def test_confirmar_pedido_fallido_no_toca_stock(self):
        stub = _StubGateway(result_estado=ESTADO_FALLIDO)
        recibo, init = self._crear_pedido_pendiente(stub)

        with mock.patch('ecommerce.services.get_online_gateway', return_value=stub):
            resultado = confirmar_pedido(token=init.token)

        resultado.refresh_from_db()
        self.assertEqual(resultado.estado, ReciboVenta.ESTADO_FALLIDO)
        stock = StockTienda.objects.get(tienda=self.tienda, producto=self.producto)
        self.assertEqual(stock.cantidad, 5)
        self.assertFalse(MovimientoStock.objects.exists())

    def test_confirmar_pedido_cancelado_marca_cancelado(self):
        stub = _StubGateway(result_estado=ESTADO_CANCELADO)
        recibo, init = self._crear_pedido_pendiente(stub)

        with mock.patch('ecommerce.services.get_online_gateway', return_value=stub):
            resultado = confirmar_pedido(token=init.token)

        resultado.refresh_from_db()
        self.assertEqual(resultado.estado, ReciboVenta.ESTADO_CANCELADO)

    def test_confirmar_pedido_idempotente(self):
        stub = _StubGateway(result_estado=ESTADO_PAGADO)
        recibo, init = self._crear_pedido_pendiente(stub)

        with mock.patch('ecommerce.services.get_online_gateway', return_value=stub):
            confirmar_pedido(token=init.token)
            confirmar_pedido(token=init.token)  # segunda llamada no debe re-descontar

        stock = StockTienda.objects.get(tienda=self.tienda, producto=self.producto)
        self.assertEqual(stock.cantidad, 3)
        self.assertEqual(MovimientoStock.objects.count(), 1)
        # El gateway fue consultado solo la primera vez (idempotencia).
        self.assertEqual(stub.confirmar_calls, 1)

    def test_confirmar_pedido_stock_post_pago_se_evapora_marca_fallido(self):
        stub = _StubGateway(result_estado=ESTADO_PAGADO)
        recibo, init = self._crear_pedido_pendiente(stub)

        # Simulamos que alguien vació el stock entre iniciar y confirmar.
        StockTienda.objects.filter(tienda=self.tienda, producto=self.producto).update(cantidad=0)

        with mock.patch('ecommerce.services.get_online_gateway', return_value=stub):
            resultado = confirmar_pedido(token=init.token)

        resultado.refresh_from_db()
        self.assertEqual(resultado.estado, ReciboVenta.ESTADO_FALLIDO)
        self.assertFalse(MovimientoStock.objects.exists())
