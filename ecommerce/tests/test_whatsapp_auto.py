"""Notificaciones automaticas por WhatsApp (Meta Cloud API) — flag apagada
por default; requests SIEMPRE mockeado (no toca red).
"""
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.roles import DESPACHADOR
from bodega.models import Tienda
from ecommerce import whatsapp
from pos.models import ReciboVenta

User = get_user_model()

CREDS = dict(
    FEATURE_WHATSAPP_AUTO=True,
    WHATSAPP_API_TOKEN='token-secreto',
    WHATSAPP_PHONE_NUMBER_ID='111222333',
)


def _recibo_fake(**kw):
    base = dict(pk=42, cliente_nombre='María González',
                cliente_telefono='+56 9 5544 3322', cliente_direccion='')
    base.update(kw)
    return SimpleNamespace(**base)


class EnviarPlantillaTests(TestCase):

    @mock.patch('ecommerce.whatsapp.requests.post')
    def test_flag_apagada_no_llama_a_meta(self, m_post):
        # Default del proyecto: FEATURE_WHATSAPP_AUTO=False.
        ok = whatsapp.enviar_plantilla('+56955443322', 'pedido_confirmado')
        self.assertFalse(ok)
        m_post.assert_not_called()

    @override_settings(FEATURE_WHATSAPP_AUTO=True)
    @mock.patch('ecommerce.whatsapp.requests.post')
    def test_flag_activa_sin_credenciales_no_llama(self, m_post):
        ok = whatsapp.enviar_plantilla('+56955443322', 'pedido_confirmado')
        self.assertFalse(ok)
        m_post.assert_not_called()

    @override_settings(**CREDS)
    @mock.patch('ecommerce.whatsapp.requests.post')
    def test_envia_con_payload_correcto(self, m_post):
        m_post.return_value = mock.Mock(status_code=200)
        ok = whatsapp.enviar_plantilla(
            '9 5544 3322', 'pedido_confirmado', ('María', '#42'),
        )
        self.assertTrue(ok)
        args, kwargs = m_post.call_args
        # URL del Graph API con el phone_number_id.
        self.assertIn('graph.facebook.com', args[0])
        self.assertIn('/111222333/messages', args[0])
        # Token en el header.
        self.assertEqual(kwargs['headers']['Authorization'], 'Bearer token-secreto')
        payload = kwargs['json']
        # Telefono normalizado a digitos con codigo pais.
        self.assertEqual(payload['to'], '56955443322')
        self.assertEqual(payload['template']['name'], 'pedido_confirmado')
        params = payload['template']['components'][0]['parameters']
        self.assertEqual([p['text'] for p in params], ['María', '#42'])

    @override_settings(**CREDS)
    @mock.patch('ecommerce.whatsapp.requests.post')
    def test_telefono_invalido_no_llama(self, m_post):
        ok = whatsapp.enviar_plantilla('no-es-fono', 'pedido_confirmado')
        self.assertFalse(ok)
        m_post.assert_not_called()

    @override_settings(**CREDS)
    @mock.patch('ecommerce.whatsapp.requests.post')
    def test_error_de_meta_devuelve_false(self, m_post):
        m_post.return_value = mock.Mock(status_code=401, text='bad token')
        ok = whatsapp.enviar_plantilla('+56955443322', 'pedido_confirmado')
        self.assertFalse(ok)

    @override_settings(**CREDS)
    @mock.patch('ecommerce.whatsapp.requests.post')
    def test_error_de_red_devuelve_false(self, m_post):
        import requests as req
        m_post.side_effect = req.ConnectionError('boom')
        ok = whatsapp.enviar_plantilla('+56955443322', 'pedido_confirmado')
        self.assertFalse(ok)


class NotificacionesDeNegocioTests(TestCase):

    @override_settings(**CREDS)
    @mock.patch('ecommerce.whatsapp.requests.post')
    def test_pedido_listo_retiro_sin_direccion(self, m_post):
        m_post.return_value = mock.Mock(status_code=200)
        whatsapp.notificar_pedido_listo(_recibo_fake(cliente_direccion=''))
        payload = m_post.call_args.kwargs['json']
        self.assertEqual(payload['template']['name'], 'pedido_listo_retiro')

    @override_settings(**CREDS)
    @mock.patch('ecommerce.whatsapp.requests.post')
    def test_pedido_despachado_con_direccion(self, m_post):
        m_post.return_value = mock.Mock(status_code=200)
        whatsapp.notificar_pedido_listo(
            _recibo_fake(cliente_direccion='Av. Siempreviva 123'))
        payload = m_post.call_args.kwargs['json']
        self.assertEqual(payload['template']['name'], 'pedido_despachado')

    @override_settings(**CREDS)
    @mock.patch('ecommerce.whatsapp.requests.post')
    def test_sin_telefono_no_notifica(self, m_post):
        ok = whatsapp.notificar_pedido_confirmado(
            _recibo_fake(cliente_telefono=''))
        self.assertFalse(ok)
        m_post.assert_not_called()


class HookDespachoTests(TestCase):
    """Marcar despachado dispara la notificacion (cuando esta activa)."""

    def setUp(self):
        self.tienda = Tienda.objects.create(
            nombre_organizacion='Online', activa=True)
        self.user = User.objects.create_user('despachadora', password='x')
        self.user.groups.add(Group.objects.get(name=DESPACHADOR))
        self.client.force_login(self.user)
        self.pedido = ReciboVenta.objects.create(
            tienda=self.tienda,
            canal=ReciboVenta.CANAL_ONLINE,
            estado=ReciboVenta.ESTADO_PAGADO,
            total=Decimal('19990'),
            cliente_nombre='María González',
            cliente_telefono='+56955443322',
        )

    @override_settings(**CREDS)
    @mock.patch('ecommerce.whatsapp.requests.post')
    def test_marcar_despachado_notifica(self, m_post):
        m_post.return_value = mock.Mock(status_code=200)
        resp = self.client.post(
            reverse('despacho:marcar_despachado', args=[self.pedido.pk]))
        self.assertEqual(resp.status_code, 302)
        m_post.assert_called_once()
        payload = m_post.call_args.kwargs['json']
        self.assertEqual(payload['template']['name'], 'pedido_listo_retiro')

    @mock.patch('ecommerce.whatsapp.requests.post')
    def test_con_flag_apagada_el_flujo_no_cambia(self, m_post):
        resp = self.client.post(
            reverse('despacho:marcar_despachado', args=[self.pedido.pk]))
        self.assertEqual(resp.status_code, 302)
        self.pedido.refresh_from_db()
        self.assertIsNotNone(self.pedido.despachado_en)
        m_post.assert_not_called()
