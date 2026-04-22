"""Tests del servicio procesar_venta (checkout atómico)."""

from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from bodega.models import MovimientoStock, StockTienda, Tienda
from catalogo.models import Familia, Producto, ProductoVariante
from pos.models import ReciboVenta, ReciboVentaDetalle
from pos.payments import ESTADO_FALLIDO, PaymentGateway, PaymentResult
from pos.services import (
    CobroFallido,
    ItemVenta,
    StockInsuficiente,
    procesar_venta,
)


User = get_user_model()


class _FailingGateway(PaymentGateway):
    provider = 'test-fail'

    def cobrar(self, recibo):
        return PaymentResult(
            estado=ESTADO_FALLIDO,
            provider=self.provider,
            reference='',
            detalle='rechazado por test',
        )


@override_settings(PAYMENT_GATEWAY='mock')
class ProcesarVentaTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.familia = Familia.objects.create(nombre='Perfumes')
        cls.tienda = Tienda.objects.create(nombre_organizacion='Tienda Test', activa=True)
        cls.cajero = User.objects.create_user(username='caja1', password='x')

        cls.producto = Producto.objects.create(
            familia=cls.familia,
            nombre='Perfume 30ml',
            precio_base=Decimal('10000'),
            tiene_variantes=False,
        )
        cls.producto_var = Producto.objects.create(
            familia=cls.familia,
            nombre='Polera',
            precio_base=Decimal('5000'),
            tiene_variantes=True,
        )
        cls.variante = ProductoVariante.objects.create(
            producto=cls.producto_var,
            sku='POL-M',
            precio_override=Decimal('9000'),
        )
        StockTienda.objects.create(tienda=cls.tienda, producto=cls.producto, cantidad=5)
        StockTienda.objects.create(tienda=cls.tienda, variante=cls.variante, cantidad=3)

    def _item(self, tipo, obj, cantidad, precio):
        return ItemVenta(
            tipo=tipo,
            item_id=obj.pk,
            cantidad=cantidad,
            precio_unitario=Decimal(precio),
            descuento_total=Decimal('0'),
        )

    def test_checkout_exitoso_crea_recibo_pagado_y_descuenta_stock(self):
        items = [
            self._item('p', self.producto, 2, '10000'),
            self._item('v', self.variante, 1, '9000'),
        ]
        recibo = procesar_venta(
            tienda=self.tienda,
            vendedor=self.cajero,
            items=items,
        )

        self.assertEqual(recibo.estado, ReciboVenta.ESTADO_PAGADO)
        self.assertEqual(recibo.total, Decimal('29000'))
        self.assertEqual(recibo.payment_provider, 'mock')
        self.assertTrue(recibo.payment_idempotency_key)

        self.assertEqual(recibo.detalles.count(), 2)

        # Stock descontado
        stock_p = StockTienda.objects.get(tienda=self.tienda, producto=self.producto)
        stock_v = StockTienda.objects.get(tienda=self.tienda, variante=self.variante)
        self.assertEqual(stock_p.cantidad, 3)
        self.assertEqual(stock_v.cantidad, 2)

        # Auditoría de movimientos
        movs = MovimientoStock.objects.filter(tienda=self.tienda, tipo=MovimientoStock.SALIDA)
        self.assertEqual(movs.count(), 2)
        self.assertTrue(all(m.referencia == f'Recibo #{recibo.pk}' for m in movs))

    def test_checkout_falla_por_stock_insuficiente_y_revierte(self):
        items = [self._item('p', self.producto, 99, '10000')]

        with self.assertRaises(StockInsuficiente):
            procesar_venta(tienda=self.tienda, vendedor=self.cajero, items=items)

        # No se creó recibo ni se tocó stock.
        self.assertFalse(ReciboVenta.objects.exists())
        self.assertFalse(ReciboVentaDetalle.objects.exists())
        stock = StockTienda.objects.get(tienda=self.tienda, producto=self.producto)
        self.assertEqual(stock.cantidad, 5)
        self.assertFalse(MovimientoStock.objects.filter(tipo=MovimientoStock.SALIDA).exists())

    def test_checkout_falla_por_cobro_revierte_todo(self):
        items = [self._item('p', self.producto, 2, '10000')]

        with mock.patch('pos.services.get_gateway', return_value=_FailingGateway()):
            with self.assertRaises(CobroFallido):
                procesar_venta(tienda=self.tienda, vendedor=self.cajero, items=items)

        # La transacción atómica revierte todo: no quedan recibos ni detalles.
        self.assertFalse(ReciboVenta.objects.exists())
        self.assertFalse(ReciboVentaDetalle.objects.exists())

        # Stock intacto y sin movimientos auditados.
        stock = StockTienda.objects.get(tienda=self.tienda, producto=self.producto)
        self.assertEqual(stock.cantidad, 5)
        self.assertFalse(MovimientoStock.objects.filter(tipo=MovimientoStock.SALIDA).exists())

    def test_items_vacios_levanta_value_error(self):
        with self.assertRaises(ValueError):
            procesar_venta(tienda=self.tienda, vendedor=self.cajero, items=[])
