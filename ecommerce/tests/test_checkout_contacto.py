"""Regresion: el checkout debe PERSISTIR telefono y direccion.

Bug historico: el form los pedia, la vista los pasaba a iniciar_pedido,
y la funcion los descartaba (el modelo no tenia los campos). El despacho
mostraba "sin telefono" / "retira en local" para TODOS los pedidos.
"""
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from bodega.models import StockTienda, Tienda
from catalogo.models import Familia, Producto
from pos.models import ReciboVenta


class CheckoutPersisteContactoTests(TestCase):

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

    def tearDown(self):
        self.override.disable()

    def test_checkout_guarda_telefono_y_direccion_en_el_recibo(self):
        # Agregar al carrito y pasar por el checkout completo.
        self.client.post(reverse('ecommerce:agregar'), {
            'tipo': 'p', 'item_id': self.producto.pk, 'cantidad': 1,
        })
        resp = self.client.post(reverse('ecommerce:checkout_iniciar'), {
            'cliente_nombre': 'María González',
            'cliente_email': 'maria@example.com',
            'cliente_telefono': '+56 9 5544 3322',
            'cliente_direccion': 'Av. Siempreviva 123, Los Vilos',
            'gateway': 'mock',
        })
        self.assertEqual(resp.status_code, 302)

        recibo = ReciboVenta.objects.latest('pk')
        self.assertEqual(recibo.cliente_telefono, '+56 9 5544 3322')
        self.assertEqual(recibo.cliente_direccion, 'Av. Siempreviva 123, Los Vilos')
