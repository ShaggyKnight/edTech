"""Checkout: telefono como identificador de contacto + flag de envios.

Regresion historica: el form pedia telefono/direccion, la vista los
pasaba a iniciar_pedido, y la funcion los descartaba (el modelo no
tenia los campos). El despacho mostraba "sin telefono" / "retira en
local" para TODOS los pedidos.

Ahora ademas: telefono REQUERIDO y normalizado (+569XXXXXXXX), RUT
fuera del checkout (no emitimos factura), y la direccion solo existe
si FEATURE_ENVIOS esta activa.
"""
from decimal import Decimal

from django.test import TestCase, override_settings
from django.urls import reverse

from bodega.models import StockTienda, Tienda
from catalogo.models import Familia, Producto
from pos.models import ReciboVenta


class _BaseCheckout(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.tienda = Tienda.objects.create(nombre_organizacion='Online', activa=True)
        fam = Familia.objects.create(nombre='Perfumes')
        cls.producto = Producto.objects.create(
            familia=fam, nombre='Perfume Contacto',
            precio_base=Decimal('10000'), tiene_variantes=False,
        )
        StockTienda.objects.create(
            tienda=cls.tienda, producto=cls.producto, cantidad=5,
        )

    def setUp(self):
        self.override = self.settings(
            ECOMMERCE_TIENDA_ID=self.tienda.pk,
            ECOMMERCE_GATEWAYS_ACTIVOS=['mock'],
        )
        self.override.enable()
        self.client.post(reverse('ecommerce:agregar'), {
            'tipo': 'p', 'item_id': self.producto.pk, 'cantidad': 1,
        })

    def tearDown(self):
        self.override.disable()

    def _post_checkout(self, **extra):
        data = {
            'cliente_nombre': 'María González',
            'cliente_email': 'maria@example.com',
            'cliente_telefono': '+56 9 5544 3322',
        }
        data.update(extra)
        return self.client.post(reverse('ecommerce:checkout_iniciar'), data)


class TelefonoRequeridoTests(_BaseCheckout):

    def test_telefono_se_guarda_normalizado(self):
        resp = self._post_checkout()
        self.assertEqual(resp.status_code, 302)
        recibo = ReciboVenta.objects.latest('pk')
        self.assertEqual(recibo.cliente_telefono, '+56955443322')

    def test_sin_telefono_rechaza(self):
        resp = self._post_checkout(cliente_telefono='')
        # Vuelve al form con error, no crea recibo.
        self.assertEqual(ReciboVenta.objects.count(), 0)

    def test_telefono_invalido_rechaza(self):
        resp = self._post_checkout(cliente_telefono='12345')
        self.assertEqual(ReciboVenta.objects.count(), 0)

    def test_checkout_ya_no_pide_rut(self):
        resp = self.client.get(reverse('ecommerce:checkout'))
        self.assertNotContains(resp, 'cliente_rut')
        self.assertNotContains(resp, 'para factura')


@override_settings(FEATURE_ENVIOS=False)
class SinEnviosTests(_BaseCheckout):

    def test_checkout_no_pide_direccion_y_avisa_retiro(self):
        resp = self.client.get(reverse('ecommerce:checkout'))
        self.assertNotContains(resp, 'Dirección de envío')
        self.assertContains(resp, 'Retiro en tienda')
        self.assertContains(resp, 'Caupolicán 437-B')

    def test_direccion_forzada_por_post_se_ignora(self):
        """Un POST manual con direccion no debe guardarla — sin envios
        activos el despacho la interpretaria como 'hay que enviar'."""
        resp = self._post_checkout(cliente_direccion='Calle Falsa 123')
        self.assertEqual(resp.status_code, 302)
        recibo = ReciboVenta.objects.latest('pk')
        self.assertEqual(recibo.cliente_direccion, '')

    def test_pedido_publico_muestra_retiro(self):
        self._post_checkout()
        recibo = ReciboVenta.objects.latest('pk')
        self.assertEqual(recibo.cliente_direccion, '')


@override_settings(FEATURE_ENVIOS=True)
class ConEnviosTests(_BaseCheckout):

    def test_checkout_pide_direccion(self):
        resp = self.client.get(reverse('ecommerce:checkout'))
        self.assertContains(resp, 'Dirección de envío')

    def test_direccion_se_guarda(self):
        resp = self._post_checkout(
            cliente_direccion='Av. Siempreviva 123, Los Vilos',
        )
        self.assertEqual(resp.status_code, 302)
        recibo = ReciboVenta.objects.latest('pk')
        self.assertEqual(recibo.cliente_direccion, 'Av. Siempreviva 123, Los Vilos')
