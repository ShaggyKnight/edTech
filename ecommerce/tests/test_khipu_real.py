"""Tests de la integracion REAL de Khipu (API v3) — requests mockeado.

Cubre: headers x-api-key, payload de creacion, notify_url bien armada,
mapeo de estados y verificacion de firma HMAC del webhook (base64).
"""
import base64
import hashlib
import hmac
import json
import time
from decimal import Decimal
from unittest import mock

from django.test import RequestFactory, TestCase, override_settings

from bodega.models import Tienda
from ecommerce.gateways.khipu import KhipuGateway
from pos.models import ReciboVenta
from pos.payments import (
    ESTADO_CANCELADO, ESTADO_FALLIDO, ESTADO_PAGADO, ESTADO_PENDIENTE,
)

API_KEY = 'test-api-key-123'
SECRET = 'llave-cobrador-abc'
RETURN_URL = 'https://ideasboutique.cl/tienda/checkout/retorno/'


def _recibo(**kwargs):
    tienda = Tienda.objects.create(nombre_organizacion='Online', activa=True)
    defaults = dict(
        tienda=tienda,
        canal=ReciboVenta.CANAL_ONLINE,
        total=Decimal('19990'),
        cliente_nombre='Ana Prueba',
        cliente_email='ana@example.com',
    )
    defaults.update(kwargs)
    return ReciboVenta.objects.create(**defaults)


def _firma_khipu(body: bytes, secret: str, ts_ms: int) -> str:
    """Genera el header x-khipu-signature como lo manda Khipu (base64)."""
    firmable = f'{ts_ms}.'.encode('utf-8') + body
    digest = hmac.new(secret.encode('utf-8'), firmable, hashlib.sha256).digest()
    return f't={ts_ms},s={base64.b64encode(digest).decode("ascii")}'


@override_settings(KHIPU_API_KEY=API_KEY, KHIPU_SECRET=SECRET)
class KhipuIniciarPagoTests(TestCase):

    @mock.patch('ecommerce.gateways.khipu.requests.post')
    def test_crea_pago_con_headers_y_payload_correctos(self, m_post):
        m_post.return_value = mock.Mock(
            status_code=201,
            json=lambda: {
                'payment_id': 'pay_abc123',
                'payment_url': 'https://khipu.com/pay/abc123',
                'simplified_transfer_url': 'https://app.khipu.com/pay/abc123',
            },
        )
        recibo = _recibo()
        init = KhipuGateway().iniciar_pago(recibo, RETURN_URL)

        # Se llamo al endpoint v3 con x-api-key (NO Bearer).
        args, kwargs = m_post.call_args
        self.assertEqual(args[0], 'https://payment-api.khipu.com/v3/payments')
        self.assertEqual(kwargs['headers']['x-api-key'], API_KEY)
        self.assertNotIn('Authorization', kwargs['headers'])

        payload = kwargs['json']
        self.assertEqual(payload['amount'], 19990)       # int, sin decimales
        self.assertEqual(payload['currency'], 'CLP')
        self.assertEqual(payload['transaction_id'], f'IBR-{recibo.pk:08d}')
        self.assertEqual(payload['return_url'], RETURN_URL)
        # El default del panel es la notificacion 1.3 (legacy, sin firma)
        # — exigimos la 3.0 explicitamente o el webhook rechazaria todo.
        self.assertEqual(payload['notify_api_version'], '3.0')
        # notify_url apunta a la ruta REAL del webhook (no un replace
        # fragil sobre el path del retorno).
        self.assertEqual(
            payload['notify_url'],
            'https://ideasboutique.cl/tienda/pago/webhook/khipu/',
        )

        # Preferimos la URL simplificada; token = payment_id.
        self.assertEqual(init.redirect_url, 'https://app.khipu.com/pay/abc123')
        self.assertEqual(init.token, 'pay_abc123')
        self.assertEqual(init.provider, 'khipu')

    @mock.patch('ecommerce.gateways.khipu.requests.post')
    def test_error_http_levanta_gateway_error(self, m_post):
        from pos.payments import PaymentGatewayError
        m_post.return_value = mock.Mock(status_code=403, text='bad key')
        with self.assertRaises(PaymentGatewayError):
            KhipuGateway().iniciar_pago(_recibo(), RETURN_URL)


@override_settings(KHIPU_API_KEY=API_KEY, KHIPU_SECRET=SECRET)
class KhipuConfirmarPagoTests(TestCase):

    def _gw_con_respuesta(self, m_get, data, status=200):
        m_get.return_value = mock.Mock(status_code=status, json=lambda: data,
                                       text=json.dumps(data))
        return KhipuGateway()

    @mock.patch('ecommerce.gateways.khipu.requests.get')
    def test_done_mapea_a_pagado(self, m_get):
        gw = self._gw_con_respuesta(m_get, {'payment_id': 'p1', 'status': 'done'})
        r = gw.confirmar_pago('p1')
        self.assertEqual(r.estado, ESTADO_PAGADO)
        self.assertEqual(r.reference, 'p1')
        # Consulto el pago por id con la api key.
        args, kwargs = m_get.call_args
        self.assertEqual(args[0], 'https://payment-api.khipu.com/v3/payments/p1')
        self.assertEqual(kwargs['headers']['x-api-key'], API_KEY)

    @mock.patch('ecommerce.gateways.khipu.requests.get')
    def test_verifying_y_pending_quedan_pendientes(self, m_get):
        for st in ('verifying', 'pending'):
            gw = self._gw_con_respuesta(m_get, {'payment_id': 'p', 'status': st})
            self.assertEqual(gw.confirmar_pago('p').estado, ESTADO_PENDIENTE)

    @mock.patch('ecommerce.gateways.khipu.requests.get')
    def test_status_detail_degrada_el_estado(self, m_get):
        gw = self._gw_con_respuesta(m_get, {
            'payment_id': 'p', 'status': 'done',
            'status_detail': 'rejected_by_payer',
        })
        self.assertEqual(gw.confirmar_pago('p').estado, ESTADO_FALLIDO)

        gw = self._gw_con_respuesta(m_get, {
            'payment_id': 'p', 'status': 'done', 'status_detail': 'reversed',
        })
        self.assertEqual(gw.confirmar_pago('p').estado, ESTADO_CANCELADO)

    @mock.patch('ecommerce.gateways.khipu.requests.get')
    def test_error_de_red_devuelve_pendiente_no_fallido(self, m_get):
        import requests as req
        m_get.side_effect = req.ConnectionError('boom')
        r = KhipuGateway().confirmar_pago('p1')
        # Un blip de red no puede marcar fallido un pago que quiza salio
        # bien — pendiente deja que el webhook o un refresh lo resuelva.
        self.assertEqual(r.estado, ESTADO_PENDIENTE)


@override_settings(KHIPU_API_KEY=API_KEY, KHIPU_SECRET=SECRET)
class KhipuWebhookTests(TestCase):

    def _request(self, data: dict, header: str = None, secret=SECRET):
        body = json.dumps(data).encode('utf-8')
        if header is None:
            header = _firma_khipu(body, secret, int(time.time() * 1000))
        return RequestFactory().post(
            '/tienda/pago/webhook/khipu/', data=body,
            content_type='application/json',
            HTTP_X_KHIPU_SIGNATURE=header,
        )

    def test_firma_valida_procesa_y_parsea_recibo(self):
        req = self._request({
            'payment_id': 'pay_9', 'transaction_id': 'IBR-00000042',
            'status': 'done',
        })
        result = KhipuGateway().webhook(req)
        self.assertTrue(result.handled)
        self.assertEqual(result.recibo_pk, 42)
        self.assertEqual(result.payment_result.estado, ESTADO_PAGADO)

    def test_firma_invalida_se_ignora(self):
        req = self._request(
            {'payment_id': 'p', 'transaction_id': 'IBR-00000001',
             'status': 'done'},
            secret='otra-llave-equivocada',
        )
        result = KhipuGateway().webhook(req)
        self.assertFalse(result.handled)
        self.assertIsNone(result.payment_result)

    def test_timestamp_viejo_se_rechaza(self):
        data = {'payment_id': 'p', 'transaction_id': 'IBR-00000001',
                'status': 'done'}
        body = json.dumps(data).encode('utf-8')
        ts_viejo = int((time.time() - 3600) * 1000)  # 1 hora atras
        req = self._request(data, header=_firma_khipu(body, SECRET, ts_viejo))
        self.assertFalse(KhipuGateway().webhook(req).handled)

    def test_sin_header_se_ignora(self):
        body = json.dumps({'status': 'done'}).encode('utf-8')
        req = RequestFactory().post(
            '/tienda/pago/webhook/khipu/', data=body,
            content_type='application/json',
        )
        self.assertFalse(KhipuGateway().webhook(req).handled)


class KhipuMockModeTests(TestCase):
    """Sin KHIPU_API_KEY el gateway sigue siendo el simulador local."""

    @override_settings(KHIPU_API_KEY='')
    def test_sin_api_key_usa_mock(self):
        gw = KhipuGateway()
        self.assertTrue(gw.mock_mode)
        r = gw.confirmar_pago('KHIPU-MOCK-1')
        self.assertEqual(r.estado, ESTADO_PAGADO)
