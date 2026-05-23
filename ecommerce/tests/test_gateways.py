"""Tests del sistema multi-gateway online (KLAP + Khipu + mock)."""

from __future__ import annotations

import hashlib
import hmac
import json
from decimal import Decimal

from django.test import RequestFactory, TestCase, override_settings

from bodega.models import Tienda
from catalogo.models import Familia, Producto
from ecommerce.gateways import (
    get_gateway, get_gateway_default, get_gateways_activos,
)
from ecommerce.gateways.base import OnlinePaymentInit, WebhookResult
from ecommerce.gateways.klap import KlapGateway
from ecommerce.gateways.khipu import KhipuGateway
from ecommerce.gateways.mock import MockOnlineGateway
from pos.models import ReciboVenta
from pos.payments import (
    ESTADO_CANCELADO, ESTADO_FALLIDO, ESTADO_PAGADO, ESTADO_PENDIENTE,
)


class GatewayRegistryTests(TestCase):
    """get_gateway, get_gateways_activos, fallback default."""

    def test_get_gateway_mock(self):
        gw = get_gateway('mock')
        self.assertIsInstance(gw, MockOnlineGateway)
        self.assertEqual(gw.provider, 'mock')

    def test_get_gateway_klap(self):
        gw = get_gateway('klap')
        self.assertIsInstance(gw, KlapGateway)
        # Sin credenciales en .env, KLAP arranca en mock_mode.
        self.assertTrue(gw.mock_mode)

    def test_get_gateway_khipu(self):
        gw = get_gateway('khipu')
        self.assertIsInstance(gw, KhipuGateway)
        self.assertTrue(gw.mock_mode)

    def test_get_gateway_desconocido_lanza_keyerror(self):
        with self.assertRaises(KeyError):
            get_gateway('paypal')  # no implementado

    @override_settings(
        ECOMMERCE_GATEWAYS_ACTIVOS=['klap', 'khipu', 'mock'],
        ECOMMERCE_GATEWAY_DEFAULT='',  # sin default forzado
    )
    def test_get_gateways_activos_devuelve_lista_en_orden(self):
        gws = get_gateways_activos()
        self.assertEqual([g.provider for g in gws], ['klap', 'khipu', 'mock'])

    @override_settings(
        ECOMMERCE_GATEWAYS_ACTIVOS=['klap', 'khipu'],
        ECOMMERCE_GATEWAY_DEFAULT='khipu',
    )
    def test_default_va_primero(self):
        gws = get_gateways_activos()
        self.assertEqual(gws[0].provider, 'khipu')

    @override_settings(
        ECOMMERCE_GATEWAYS_ACTIVOS=[],
        ECOMMERCE_GATEWAY_DEFAULT='',
    )
    def test_lista_vacia_fallback_a_mock(self):
        gw = get_gateway_default()
        self.assertEqual(gw.provider, 'mock')


class KlapWebhookTests(TestCase):
    """KLAP webhook con validacion de firma HMAC."""

    @classmethod
    def setUpTestData(cls):
        cls.familia = Familia.objects.create(nombre='Perfumes')
        cls.tienda = Tienda.objects.create(nombre_organizacion='T', activa=True)

    def setUp(self):
        self.factory = RequestFactory()
        self.recibo = ReciboVenta.objects.create(
            canal=ReciboVenta.CANAL_ONLINE,
            tienda=self.tienda,
            total=Decimal('15000'),
            estado=ReciboVenta.ESTADO_PENDIENTE,
            payment_provider='klap',
            payment_reference='KLAP-TX-42',
        )

    @override_settings(
        KLAP_COMMERCE_ID='c1', KLAP_API_KEY='k1',
        KLAP_WEBHOOK_SECRET='shhh-secret',
    )
    def test_webhook_firma_valida_devuelve_resultado(self):
        gw = KlapGateway()
        body = json.dumps({
            'transaction_id': 'KLAP-TX-42',
            'merchant_reference': f'IBR-{self.recibo.pk:08d}',
            'status': 'approved',
            'authorization_code': 'AUTH-XYZ',
        }).encode('utf-8')
        firma = hmac.new(
            b'shhh-secret', body, hashlib.sha256,
        ).hexdigest()
        req = self.factory.post(
            '/tienda/pago/webhook/klap/', body,
            content_type='application/json',
            HTTP_X_KLAP_SIGNATURE=f'sha256={firma}',
        )
        result = gw.webhook(req)
        self.assertTrue(result.handled)
        self.assertEqual(result.recibo_pk, self.recibo.pk)
        self.assertEqual(result.payment_result.estado, ESTADO_PAGADO)

    @override_settings(
        KLAP_COMMERCE_ID='c1', KLAP_API_KEY='k1',
        KLAP_WEBHOOK_SECRET='shhh-secret',
    )
    def test_webhook_firma_invalida_no_se_procesa(self):
        gw = KlapGateway()
        body = json.dumps({'status': 'approved'}).encode('utf-8')
        req = self.factory.post(
            '/tienda/pago/webhook/klap/', body,
            content_type='application/json',
            HTTP_X_KLAP_SIGNATURE='sha256=firma-mentirosa',
        )
        result = gw.webhook(req)
        self.assertFalse(result.handled)
        self.assertEqual(result.recibo_pk, None)


class KhipuWebhookTests(TestCase):
    """Khipu webhook con HMAC firma+timestamp."""

    @classmethod
    def setUpTestData(cls):
        cls.familia = Familia.objects.create(nombre='Perfumes')
        cls.tienda = Tienda.objects.create(nombre_organizacion='T', activa=True)

    def setUp(self):
        self.factory = RequestFactory()
        self.recibo = ReciboVenta.objects.create(
            canal=ReciboVenta.CANAL_ONLINE,
            tienda=self.tienda,
            total=Decimal('15000'),
            estado=ReciboVenta.ESTADO_PENDIENTE,
        )

    @override_settings(KHIPU_RECEIVER_ID='r1', KHIPU_SECRET='topsecret')
    def test_webhook_firma_valida(self):
        gw = KhipuGateway()
        body = json.dumps({
            'payment_id': 'pay_abc',
            'transaction_id': f'IBR-{self.recibo.pk:08d}',
            'status': 'done',
        }).encode('utf-8')
        timestamp = '1729550000'
        firma_obj = hmac.new(
            b'topsecret', f'{timestamp}.'.encode('utf-8') + body,
            hashlib.sha256,
        ).hexdigest()
        req = self.factory.post(
            '/tienda/pago/webhook/khipu/', body,
            content_type='application/json',
            HTTP_X_KHIPU_SIGNATURE=f't={timestamp},s={firma_obj}',
        )
        result = gw.webhook(req)
        self.assertTrue(result.handled)
        self.assertEqual(result.recibo_pk, self.recibo.pk)
        self.assertEqual(result.payment_result.estado, ESTADO_PAGADO)


class CheckoutMultiGatewayTests(TestCase):
    """Vista checkout con multiples gateways activos."""

    @classmethod
    def setUpTestData(cls):
        cls.familia = Familia.objects.create(nombre='Perfumes')
        cls.tienda = Tienda.objects.create(nombre_organizacion='T', activa=True)
        cls.producto = Producto.objects.create(
            familia=cls.familia, nombre='Test',
            precio_base=Decimal('10000'), tiene_variantes=False,
        )

    @override_settings(
        ECOMMERCE_GATEWAYS_ACTIVOS=['klap', 'khipu'],
        ECOMMERCE_TIENDA_ID=1,
    )
    def test_checkout_muestra_selector_cuando_hay_mas_de_uno(self):
        # Agregar item al carrito para que el checkout no redirija.
        session = self.client.session
        from ecommerce.cart import Cart
        cart = Cart(session)
        cart.add_producto(self.producto.pk, cantidad=1)
        session.save()

        resp = self.client.get('/tienda/checkout/')
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        # Radio buttons visibles para ambos gateways
        self.assertIn('name="gateway" value="klap"', body)
        self.assertIn('name="gateway" value="khipu"', body)

    @override_settings(
        ECOMMERCE_GATEWAYS_ACTIVOS=['klap'],
        ECOMMERCE_TIENDA_ID=1,
    )
    def test_checkout_no_muestra_selector_con_un_solo_gateway(self):
        session = self.client.session
        from ecommerce.cart import Cart
        cart = Cart(session)
        cart.add_producto(self.producto.pk, cantidad=1)
        session.save()

        resp = self.client.get('/tienda/checkout/')
        body = resp.content.decode()
        # Input hidden con el unico gateway
        self.assertIn('type="hidden" name="gateway" value="klap"', body)
        # No radio buttons
        self.assertNotIn('type="radio" name="gateway"', body)
