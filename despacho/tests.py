"""Tests del despacho: tag de WhatsApp con mensaje prellenado."""
from decimal import Decimal
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.roles import DESPACHADOR
from bodega.models import Tienda
from despacho.templatetags.despacho_tags import (
    _normalizar_fono_cl, wa_aviso_pedido,
)
from pos.models import ReciboVenta

User = get_user_model()


class NormalizarFonoTests(TestCase):

    def test_formatos_tipicos_chilenos(self):
        casos = {
            '+56 9 5544 3322': '56955443322',
            '56955443322':     '56955443322',
            '9 5544 3322':     '56955443322',
            '955443322':       '56955443322',
            '55443322':        '56955443322',   # celular viejo sin 9
            '':                '',
            None:              '',
            'sin teléfono':    '',
        }
        for entrada, esperado in casos.items():
            self.assertEqual(_normalizar_fono_cl(entrada), esperado,
                             f'entrada={entrada!r}')


class WaAvisoPedidoTests(TestCase):

    def _pedido(self, **kw):
        base = dict(
            pk=42, cliente_nombre='María González',
            cliente_telefono='+56 9 5544 3322',
            cliente_direccion='Av. Siempreviva 123',
            despachado_en=timezone.now(),
        )
        base.update(kw)
        return SimpleNamespace(**base)

    def test_despachado_con_direccion_dice_en_camino(self):
        url = wa_aviso_pedido(self._pedido())
        self.assertTrue(url.startswith('https://wa.me/56955443322?text='))
        self.assertIn('va%20en%20camino', url)
        self.assertIn('Mar%C3%ADa', url)      # primer nombre
        self.assertIn('%2342', url)           # numero de pedido (#42)

    def test_despachado_sin_direccion_dice_retiro(self):
        url = wa_aviso_pedido(self._pedido(cliente_direccion=''))
        self.assertIn('listo%20para%20retiro', url)
        self.assertIn('Caupolic%C3%A1n%20437-B', url)

    def test_en_cola_dice_preparando(self):
        url = wa_aviso_pedido(self._pedido(despachado_en=None))
        self.assertIn('lo%20estamos%20preparando', url)

    def test_sin_telefono_devuelve_vacio(self):
        self.assertEqual(wa_aviso_pedido(self._pedido(cliente_telefono='')), '')


class DetalleConWhatsAppTests(TestCase):

    def setUp(self):
        self.tienda = Tienda.objects.create(
            nombre_organizacion='Online', activa=True)
        self.user = User.objects.create_user('despachadora', password='x')
        self.user.groups.add(Group.objects.get(name=DESPACHADOR))
        self.client.force_login(self.user)

    def _crear_pedido(self, telefono='+56 9 5544 3322'):
        return ReciboVenta.objects.create(
            tienda=self.tienda,
            canal=ReciboVenta.CANAL_ONLINE,
            estado=ReciboVenta.ESTADO_PAGADO,
            total=Decimal('19990'),
            cliente_nombre='María González',
            cliente_telefono=telefono,
        )

    def test_detalle_muestra_boton_whatsapp(self):
        pedido = self._crear_pedido()
        resp = self.client.get(reverse('despacho:detalle', args=[pedido.pk]))
        self.assertContains(resp, 'https://wa.me/56955443322')
        self.assertContains(resp, 'Avisar por WhatsApp')

    def test_sin_telefono_no_hay_boton(self):
        pedido = self._crear_pedido(telefono='')
        resp = self.client.get(reverse('despacho:detalle', args=[pedido.pk]))
        self.assertNotContains(resp, 'wa.me')
