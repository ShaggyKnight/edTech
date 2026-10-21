"""Mejoras de la tienda publica tras la revision de diseño.

- robots.txt ya no publica la ruta secreta del admin; el admin se oculta
  de los buscadores con la cabecera X-Robots-Tag.
- Los precios "desde" de la landing salen del catalogo, no del HTML.
- El checkout pide nombre, email y celular con autocompletar y el
  teclado correcto, y cada etiqueta apunta a su campo.
"""

from decimal import Decimal

from django.test import TestCase, override_settings
from django.urls import reverse

from bodega.models import StockTienda, Tienda
from catalogo.models import Familia, Producto
from ecommerce.forms import CheckoutForm


class RobotsAdminTests(TestCase):

    @override_settings(ADMIN_URL='panel-secreto-x9/')
    def test_robots_no_publica_la_ruta_del_admin(self):
        resp = self.client.get('/robots.txt')
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn('panel-secreto-x9', resp.content.decode())
        self.assertContains(resp, 'Disallow: /pos/')

    def test_admin_responde_con_noindex(self):
        from django.conf import settings
        resp = self.client.get('/' + settings.ADMIN_URL)
        self.assertEqual(resp['X-Robots-Tag'], 'noindex, nofollow')

    def test_pagina_publica_sin_noindex(self):
        resp = self.client.get('/robots.txt')
        self.assertNotIn('X-Robots-Tag', resp)


class PreciosLandingTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.tienda = Tienda.objects.create(nombre_organizacion='T', activa=True)
        fam = Familia.objects.create(nombre='Uniformes Escolares')
        buzo = Producto.objects.create(
            familia=fam, nombre='Buzo SFJ Chaqueta',
            precio_base=Decimal('13900'), tiene_variantes=False,
        )
        buzo_caro = Producto.objects.create(
            familia=fam, nombre='Buzo SFJ Completo',
            precio_base=Decimal('21900'), tiene_variantes=False,
        )
        sueter = Producto.objects.create(
            familia=fam, nombre='Suéter SFJ',
            precio_base=Decimal('16900'), tiene_variantes=False,
        )
        # Polera sin stock: no debe dar precio.
        polera = Producto.objects.create(
            familia=fam, nombre='Polera piqué SFJ',
            precio_base=Decimal('12900'), tiene_variantes=False,
        )
        for p, cant in ((buzo, 3), (buzo_caro, 2), (sueter, 1), (polera, 0)):
            StockTienda.objects.create(tienda=cls.tienda, producto=p, cantidad=cant)

    def get_landing(self):
        with self.settings(ECOMMERCE_TIENDA_ID=self.tienda.pk):
            return self.client.get(reverse('index'))

    def test_precio_desde_es_el_minimo_con_stock(self):
        precios = self.get_landing().context['precios_desde']
        self.assertEqual(precios['buzos'], Decimal('13900'))
        self.assertEqual(precios['chalecos'], Decimal('16900'))  # suéter, sin tilde
        self.assertNotIn('poleras', precios)
        self.assertNotIn('faldas', precios)

    def test_landing_no_trae_precios_inventados(self):
        resp = self.get_landing()
        for viejo in ('$24.990', '$9.990', '$18.990'):
            self.assertNotContains(resp, viejo)

    def test_sin_tienda_configurada_no_rompe(self):
        with self.settings(ECOMMERCE_TIENDA_ID=None):
            resp = self.client.get(reverse('index'))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['precios_desde'], {})


class CheckoutCamposTests(TestCase):

    def test_campos_con_autocompletar_y_teclado(self):
        html = str(CheckoutForm())
        self.assertIn('autocomplete="name"', html)
        self.assertIn('autocomplete="email"', html)
        self.assertIn('type="tel"', html)
        self.assertIn('inputmode="tel"', html)
        self.assertIn('autocomplete="tel"', html)
