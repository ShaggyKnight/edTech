"""Meta Pixel (Facebook/Instagram Ads) + conversión de compra.

- El pixel solo existe en la página si META_PIXEL_ID está seteado.
- Es publicidad: vive detrás del gestor de consentimiento (Ley 21.719) y
  se carga recién cuando el visitante acepta esa categoría (lógica JS —
  acá verificamos que pase por window.IdeasConsent y no arranque solo).
- El evento `Purchase` se dispara UNA sola vez, igual que el de Google:
  en la primera visita a la página del pedido tras el pago.
"""
from decimal import Decimal
from urllib.parse import parse_qs, urlparse

from django.test import TestCase, override_settings
from django.urls import reverse

from bodega.models import StockTienda, Tienda
from catalogo.models import Familia, Producto
from pos.models import ReciboVenta


class MetaPixelBaseTests(TestCase):

    @override_settings(META_PIXEL_ID='111222333')
    def test_pixel_presente_cuando_esta_configurado(self):
        resp = self.client.get(reverse('index'))
        self.assertContains(resp, 'connect.facebook.net')
        # No arranca a ciegas: el ID va a la config del gestor de
        # consentimiento y el init solo corre con la publicidad aceptada.
        self.assertContains(resp, "meta: '111222333'")
        self.assertContains(resp, 'window.IdeasConsent')
        self.assertNotContains(resp, "fbq('init', '111222333')")

    @override_settings(META_PIXEL_ID='')
    def test_sin_id_no_hay_pixel(self):
        resp = self.client.get(reverse('index'))
        self.assertNotContains(resp, 'connect.facebook.net')

    @override_settings(META_PIXEL_ID='111222333')
    def test_aviso_cookies_ofrece_publicidad_con_pixel(self):
        resp = self.client.get(reverse('index'))
        self.assertContains(resp, 'id="consent-publicidad"')
        self.assertContains(resp, 'Instagram y Facebook')

    @override_settings(META_PIXEL_ID='', GOOGLE_TAG_ID='', CLARITY_PROJECT_ID='abc')
    def test_aviso_cookies_sin_pixel_no_ofrece_publicidad(self):
        resp = self.client.get(reverse('index'))
        self.assertContains(resp, 'id="consent-analitica"')
        self.assertNotContains(resp, 'id="consent-publicidad"')
        self.assertNotContains(resp, 'Instagram y Facebook')


@override_settings(META_PIXEL_ID='111222333')
class MetaConversionCompraTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.tienda = Tienda.objects.create(nombre_organizacion='Online', activa=True)
        fam = Familia.objects.create(nombre='Perfumes')
        cls.producto = Producto.objects.create(
            familia=fam, nombre='Perfume Meta',
            precio_base=Decimal('19990'), tiene_variantes=False,
        )
        StockTienda.objects.create(tienda=cls.tienda, producto=cls.producto, cantidad=5)

    def _comprar(self):
        self.client.post(reverse('ecommerce:agregar'), {
            'tipo': 'p', 'item_id': self.producto.pk, 'cantidad': 1,
        })
        resp = self.client.post(reverse('ecommerce:checkout_iniciar'), {
            'cliente_nombre': 'Ana Meta',
            'cliente_email': 'ana@example.com',
            'cliente_telefono': '+56955443322',
        })
        params = parse_qs(urlparse(resp['Location']).query)
        token, return_url = params['token'][0], params['return_url'][0]
        resp = self.client.post(
            reverse('ecommerce:mock_pago') + f'?token={token}&return_url={return_url}',
            {'decision': 'aprobar'},
        )
        return self.client.get(resp['Location'])

    def test_purchase_se_dispara_solo_la_primera_vez(self):
        with self.settings(ECOMMERCE_TIENDA_ID=self.tienda.pk,
                           ECOMMERCE_GATEWAYS_ACTIVOS=['mock']):
            resp_retorno = self._comprar()
            url_pedido = resp_retorno['Location']

            resp1 = self.client.get(url_pedido)
            self.assertContains(resp1, "fbq('track', 'Purchase'")
            self.assertContains(resp1, "currency: 'CLP'")

            resp2 = self.client.get(url_pedido)
            self.assertNotContains(resp2, "fbq('track', 'Purchase'")

    def test_sin_pixel_no_hay_evento(self):
        with self.settings(ECOMMERCE_TIENDA_ID=self.tienda.pk,
                           ECOMMERCE_GATEWAYS_ACTIVOS=['mock'],
                           META_PIXEL_ID=''):
            resp_retorno = self._comprar()
            resp = self.client.get(resp_retorno['Location'])
            self.assertNotContains(resp, "fbq('track', 'Purchase'")
