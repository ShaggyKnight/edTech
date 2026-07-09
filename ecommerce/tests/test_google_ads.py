"""Google tag (gtag.js) + conversion de compra.

- El tag solo se inyecta si GOOGLE_TAG_ID esta seteado.
- El evento `purchase` se dispara UNA sola vez: en la primera visita a
  la pagina del pedido despues del pago (el cliente la revisita desde
  el email de la boleta — no debe contar doble en Ads).
"""
from decimal import Decimal
from urllib.parse import parse_qs, urlparse

from django.test import TestCase, override_settings
from django.urls import reverse

from bodega.models import StockTienda, Tienda
from catalogo.models import Familia, Producto
from pos.models import ReciboVenta


class GoogleTagBaseTests(TestCase):

    @override_settings(GOOGLE_TAG_ID='G-TEST123')
    def test_tag_presente_cuando_esta_configurado(self):
        resp = self.client.get(reverse('index'))
        self.assertContains(resp, 'googletagmanager.com/gtag/js?id=G-TEST123')
        self.assertContains(resp, "gtag('config', 'G-TEST123')")

    def test_sin_id_no_hay_tag(self):
        resp = self.client.get(reverse('index'))
        self.assertNotContains(resp, 'googletagmanager.com')


@override_settings(GOOGLE_TAG_ID='G-TEST123')
class ConversionCompraTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.tienda = Tienda.objects.create(nombre_organizacion='Online', activa=True)
        fam = Familia.objects.create(nombre='Perfumes')
        cls.producto = Producto.objects.create(
            familia=fam, nombre='Perfume Ads',
            precio_base=Decimal('19990'), tiene_variantes=False,
        )
        StockTienda.objects.create(tienda=cls.tienda, producto=cls.producto, cantidad=5)

    def _comprar(self):
        """Flujo completo con el gateway mock: carrito → pago → retorno."""
        self.client.post(reverse('ecommerce:agregar'), {
            'tipo': 'p', 'item_id': self.producto.pk, 'cantidad': 1,
        })
        resp = self.client.post(reverse('ecommerce:checkout_iniciar'), {
            'cliente_nombre': 'Ana Ads',
            'cliente_email': 'ana@example.com',
            'cliente_telefono': '+56955443322',
        })
        params = parse_qs(urlparse(resp['Location']).query)
        token, return_url = params['token'][0], params['return_url'][0]
        resp = self.client.post(
            reverse('ecommerce:mock_pago') + f'?token={token}&return_url={return_url}',
            {'decision': 'aprobar'},
        )
        # Retorno → redirect a la pagina del pedido.
        return self.client.get(resp['Location'])

    def test_purchase_se_dispara_solo_la_primera_vez(self):
        with self.settings(ECOMMERCE_TIENDA_ID=self.tienda.pk,
                           ECOMMERCE_GATEWAYS_ACTIVOS=['mock']):
            resp_retorno = self._comprar()
            self.assertEqual(resp_retorno.status_code, 302)
            url_pedido = resp_retorno['Location']

            recibo = ReciboVenta.objects.latest('pk')

            # 1a visita (viene del retorno): dispara la conversion.
            resp1 = self.client.get(url_pedido)
            self.assertContains(resp1, "gtag('event', 'purchase'")
            self.assertContains(resp1, f'IB-{recibo.pk}')
            self.assertContains(resp1, "currency: 'CLP'")

            # 2a visita (desde el email): NO vuelve a disparar.
            resp2 = self.client.get(url_pedido)
            self.assertNotContains(resp2, "gtag('event', 'purchase'")

    def test_sin_google_tag_no_hay_evento_aunque_sea_compra_nueva(self):
        with self.settings(ECOMMERCE_TIENDA_ID=self.tienda.pk,
                           ECOMMERCE_GATEWAYS_ACTIVOS=['mock'],
                           GOOGLE_TAG_ID=''):
            resp_retorno = self._comprar()
            resp = self.client.get(resp_retorno['Location'])
            self.assertNotContains(resp, "gtag('event', 'purchase'")
