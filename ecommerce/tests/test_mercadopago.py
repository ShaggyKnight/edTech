"""Tests de la integracion REAL de Mercado Pago (Checkout Pro) — requests
mockeado.

Cubre: auth Bearer, payload de la preferencia, elección de init_point vs
sandbox según el token, mapeo de estados por búsqueda, y verificación de
la firma x-signature del webhook (HMAC del manifest).
"""
import hashlib
import hmac
import json
import time
from decimal import Decimal
from unittest import mock

from django.test import RequestFactory, TestCase, override_settings

from bodega.models import Tienda
from ecommerce.gateways.mercadopago import MercadoPagoGateway
from pos.models import ReciboVenta
from pos.payments import (
    ESTADO_CANCELADO, ESTADO_FALLIDO, ESTADO_PAGADO, ESTADO_PENDIENTE,
)

TOKEN_PROD = 'APP_USR-1234567890'
TOKEN_TEST = 'TEST-1234567890'
SECRET = 'webhook-secret-abc'
RETURN_URL = 'https://ideasboutique.cl/tienda/checkout/retorno/'


def _recibo(**kwargs):
    tienda = Tienda.objects.create(nombre_organizacion='Online', activa=True)
    defaults = dict(
        tienda=tienda,
        canal=ReciboVenta.CANAL_ONLINE,
        total=Decimal('30510'),
        cliente_nombre='Ana Prueba',
        cliente_email='ana@example.com',
    )
    defaults.update(kwargs)
    return ReciboVenta.objects.create(**defaults)


def _firma_mp(data_id: str, request_id: str, secret: str, ts: int) -> str:
    """Genera el header x-signature como lo manda Mercado Pago."""
    manifest = f'id:{data_id};request-id:{request_id};ts:{ts};'
    digest = hmac.new(secret.encode('utf-8'), manifest.encode('utf-8'),
                      hashlib.sha256).hexdigest()
    return f'ts={ts},v1={digest}'


@override_settings(MERCADOPAGO_ACCESS_TOKEN=TOKEN_PROD,
                   MERCADOPAGO_WEBHOOK_SECRET=SECRET)
class MercadoPagoIniciarPagoTests(TestCase):

    @mock.patch('ecommerce.gateways.mercadopago.requests.post')
    def test_crea_preferencia_con_bearer_y_payload(self, m_post):
        m_post.return_value = mock.Mock(
            status_code=201,
            json=lambda: {
                'id': 'pref-999',
                'init_point': 'https://mercadopago.cl/checkout/pref-999',
                'sandbox_init_point': 'https://sandbox.mercadopago.cl/pref-999',
            },
        )
        recibo = _recibo()
        init = MercadoPagoGateway().iniciar_pago(recibo, RETURN_URL)

        args, kwargs = m_post.call_args
        self.assertEqual(args[0], 'https://api.mercadopago.com/checkout/preferences')
        self.assertEqual(kwargs['headers']['Authorization'], f'Bearer {TOKEN_PROD}')

        pref = kwargs['json']
        self.assertEqual(pref['items'][0]['unit_price'], 30510)  # int CLP
        self.assertEqual(pref['items'][0]['currency_id'], 'CLP')
        self.assertEqual(pref['external_reference'], f'IBR-{recibo.pk:08d}')
        self.assertEqual(pref['back_urls']['success'], RETURN_URL)
        self.assertEqual(pref['auto_return'], 'approved')
        self.assertEqual(
            pref['notification_url'],
            'https://ideasboutique.cl/tienda/pago/webhook/mercadopago/',
        )
        self.assertEqual(pref['payer']['email'], 'ana@example.com')

        # Token prod → init_point real. El token es el external_reference
        # (lo usa confirmar_pedido para encontrar el recibo).
        self.assertEqual(init.redirect_url, 'https://mercadopago.cl/checkout/pref-999')
        self.assertEqual(init.token, f'IBR-{recibo.pk:08d}')
        self.assertEqual(init.provider, 'mercadopago')

    @override_settings(MERCADOPAGO_ACCESS_TOKEN=TOKEN_TEST)
    @mock.patch('ecommerce.gateways.mercadopago.requests.post')
    def test_token_test_usa_sandbox_init_point(self, m_post):
        m_post.return_value = mock.Mock(
            status_code=201,
            json=lambda: {
                'id': 'pref-1',
                'init_point': 'https://mercadopago.cl/prod',
                'sandbox_init_point': 'https://sandbox.mercadopago.cl/test',
            },
        )
        init = MercadoPagoGateway().iniciar_pago(_recibo(), RETURN_URL)
        self.assertEqual(init.redirect_url, 'https://sandbox.mercadopago.cl/test')

    @mock.patch('ecommerce.gateways.mercadopago.requests.post')
    def test_error_http_levanta_gateway_error(self, m_post):
        from pos.payments import PaymentGatewayError
        m_post.return_value = mock.Mock(status_code=401, text='invalid token')
        with self.assertRaises(PaymentGatewayError):
            MercadoPagoGateway().iniciar_pago(_recibo(), RETURN_URL)


@override_settings(MERCADOPAGO_ACCESS_TOKEN=TOKEN_PROD,
                   MERCADOPAGO_WEBHOOK_SECRET=SECRET)
class MercadoPagoConfirmarPagoTests(TestCase):

    def _gw_con_busqueda(self, m_get, results, status=200):
        data = {'results': results}
        m_get.return_value = mock.Mock(status_code=status, json=lambda: data,
                                       text=json.dumps(data))
        return MercadoPagoGateway()

    @mock.patch('ecommerce.gateways.mercadopago.requests.get')
    def test_approved_mapea_a_pagado(self, m_get):
        gw = self._gw_con_busqueda(m_get, [{'id': 111, 'status': 'approved'}])
        r = gw.confirmar_pago('IBR-00000042')
        self.assertEqual(r.estado, ESTADO_PAGADO)
        self.assertEqual(r.reference, '111')
        # Busca por external_reference con el Bearer.
        args, kwargs = m_get.call_args
        self.assertEqual(args[0], 'https://api.mercadopago.com/v1/payments/search')
        self.assertEqual(kwargs['params']['external_reference'], 'IBR-00000042')
        self.assertEqual(kwargs['headers']['Authorization'], f'Bearer {TOKEN_PROD}')

    @mock.patch('ecommerce.gateways.mercadopago.requests.get')
    def test_pending_e_in_process_quedan_pendientes(self, m_get):
        for st in ('pending', 'in_process', 'authorized'):
            gw = self._gw_con_busqueda(m_get, [{'id': 1, 'status': st}])
            self.assertEqual(gw.confirmar_pago('IBR-1').estado, ESTADO_PENDIENTE)

    @mock.patch('ecommerce.gateways.mercadopago.requests.get')
    def test_rejected_fallido_y_refund_cancelado(self, m_get):
        gw = self._gw_con_busqueda(m_get, [{'id': 1, 'status': 'rejected'}])
        self.assertEqual(gw.confirmar_pago('IBR-1').estado, ESTADO_FALLIDO)
        gw = self._gw_con_busqueda(m_get, [{'id': 1, 'status': 'refunded'}])
        self.assertEqual(gw.confirmar_pago('IBR-1').estado, ESTADO_CANCELADO)

    @mock.patch('ecommerce.gateways.mercadopago.requests.get')
    def test_sin_pagos_queda_pendiente(self, m_get):
        gw = self._gw_con_busqueda(m_get, [])
        self.assertEqual(gw.confirmar_pago('IBR-1').estado, ESTADO_PENDIENTE)

    @mock.patch('ecommerce.gateways.mercadopago.requests.get')
    def test_error_de_red_devuelve_pendiente_no_fallido(self, m_get):
        import requests as req
        m_get.side_effect = req.ConnectionError('boom')
        r = MercadoPagoGateway().confirmar_pago('IBR-1')
        self.assertEqual(r.estado, ESTADO_PENDIENTE)


@override_settings(MERCADOPAGO_ACCESS_TOKEN=TOKEN_PROD,
                   MERCADOPAGO_WEBHOOK_SECRET=SECRET)
class MercadoPagoWebhookTests(TestCase):

    def _request(self, data_id='111222', request_id='req-1', ts=None,
                 secret=SECRET, tipo='payment', firma=None):
        ts = ts if ts is not None else int(time.time())
        if firma is None:
            firma = _firma_mp(data_id, request_id, secret, ts)
        url = f'/tienda/pago/webhook/mercadopago/?type={tipo}&data.id={data_id}'
        return RequestFactory().post(
            url, data=b'{}', content_type='application/json',
            HTTP_X_SIGNATURE=firma, HTTP_X_REQUEST_ID=request_id,
        )

    @mock.patch('ecommerce.gateways.mercadopago.requests.get')
    def test_firma_valida_consulta_pago_y_parsea_recibo(self, m_get):
        m_get.return_value = mock.Mock(
            status_code=200,
            json=lambda: {'id': 111222, 'status': 'approved',
                          'external_reference': 'IBR-00000042'},
        )
        result = MercadoPagoGateway().webhook(self._request(data_id='111222'))
        self.assertTrue(result.handled)
        self.assertEqual(result.recibo_pk, 42)
        self.assertEqual(result.payment_result.estado, ESTADO_PAGADO)
        # Consulto el pago por id.
        args, _ = m_get.call_args
        self.assertEqual(args[0], 'https://api.mercadopago.com/v1/payments/111222')

    def test_firma_invalida_se_ignora(self):
        req = self._request(secret='otra-llave-equivocada')
        result = MercadoPagoGateway().webhook(req)
        self.assertFalse(result.handled)
        self.assertIsNone(result.payment_result)

    def test_timestamp_viejo_se_rechaza(self):
        req = self._request(ts=int(time.time()) - 3600)  # 1 hora atrás
        self.assertFalse(MercadoPagoGateway().webhook(req).handled)

    def test_topic_no_payment_se_ignora(self):
        req = self._request(tipo='merchant_order')
        self.assertFalse(MercadoPagoGateway().webhook(req).handled)

    @override_settings(MERCADOPAGO_WEBHOOK_SECRET='')
    def test_sin_secret_configurado_se_ignora(self):
        req = self._request()
        self.assertFalse(MercadoPagoGateway().webhook(req).handled)


class MercadoPagoMockModeTests(TestCase):
    """Sin MERCADOPAGO_ACCESS_TOKEN el gateway es el simulador local."""

    @override_settings(MERCADOPAGO_ACCESS_TOKEN='')
    def test_sin_token_usa_mock(self):
        gw = MercadoPagoGateway()
        self.assertTrue(gw.mock_mode)
        r = gw.confirmar_pago('IBR-00000001')
        self.assertEqual(r.estado, ESTADO_PAGADO)

    @override_settings(MERCADOPAGO_ACCESS_TOKEN='')
    def test_mock_iniciar_redirige_a_mock_pago(self):
        init = MercadoPagoGateway().iniciar_pago(_recibo(), RETURN_URL)
        self.assertIn('/tienda/mock-pago/', init.redirect_url)
        self.assertIn('gateway=mercadopago', init.redirect_url)
        self.assertTrue(init.token.startswith('IBR-'))


@override_settings(
    ECOMMERCE_GATEWAYS_ACTIVOS=['mercadopago', 'transferencia'],
    MERCADOPAGO_ACCESS_TOKEN=TOKEN_PROD,
    TRANSFERENCIA_NOMBRE='Blanca', TRANSFERENCIA_RUT='7.152.915-0',
    TRANSFERENCIA_CUENTA='7152915',
)
class MercadoPagoRegistryTests(TestCase):

    def test_mercadopago_aparece_en_gateways_activos(self):
        from ecommerce.gateways import get_gateways_activos
        nombres = [g.provider for g in get_gateways_activos()]
        self.assertIn('mercadopago', nombres)
        self.assertIn('transferencia', nombres)

    def test_sin_token_no_aparece(self):
        with override_settings(MERCADOPAGO_ACCESS_TOKEN='',
                               ECOMMERCE_GATEWAYS_ACTIVOS=['mercadopago']):
            from ecommerce.gateways import get_gateways_activos
            # Sin token cae a mock_mode pero igual instancia (no crashea);
            # el gateway sigue disponible como simulador.
            gws = get_gateways_activos()
            self.assertEqual(len(gws), 1)
            self.assertTrue(gws[0].mock_mode)
