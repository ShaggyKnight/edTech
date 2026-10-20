"""Regresiones de URLs canonicas y datos estructurados publicos."""

import json
from html.parser import HTMLParser

from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from bodega.models import StockTienda, Tienda
from catalogo.models import Familia, Producto
from .context_processors import public_settings
from .middleware import CanonicalHostMiddleware


class SchemaParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.capture = False
        self.schemas = []

    def handle_starttag(self, tag, attrs):
        self.capture = tag == 'script' and dict(attrs).get('type') == 'application/ld+json'

    def handle_data(self, data):
        if self.capture:
            self.schemas.append(json.loads(data))

    def handle_endtag(self, tag):
        if tag == 'script':
            self.capture = False


@override_settings(SITE_URL='https://ideasboutique.cl', ALLOWED_HOSTS=['testserver', 'www.ideasboutique.cl'])
class CanonicalTests(SimpleTestCase):
    def test_conserva_categoria_y_paginacion_sin_tracking(self):
        request = RequestFactory().get('/tienda/?utm_source=instagram&cat=uniformes&page=2&fbclid=test')
        self.assertEqual(public_settings(request)['CANONICAL_URL'],
                         'https://ideasboutique.cl/tienda/?cat=uniformes&page=2')

    def test_www_redirige_con_ruta_y_parametros(self):
        request = RequestFactory().get('/tienda/?cat=perfumes', HTTP_HOST='www.ideasboutique.cl')
        response = CanonicalHostMiddleware(lambda req: HttpResponse('ok'))(request)
        self.assertEqual(response.status_code, 301)
        self.assertEqual(response['Location'], 'https://ideasboutique.cl/tienda/?cat=perfumes')

    def test_no_redirige_post_ni_otros_hosts(self):
        middleware = CanonicalHostMiddleware(lambda req: HttpResponse('ok'))
        for request in [RequestFactory().post('/tienda/checkout/', HTTP_HOST='www.ideasboutique.cl'),
                        RequestFactory().get('/')]:
            self.assertEqual(middleware(request).status_code, 200)


@override_settings(SITE_URL='https://ideasboutique.cl', USE_WHITENOISE=False)
class SchemaPublicoTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tienda = Tienda.objects.create(nombre_organizacion='Online', activa=True)
        familia = Familia.objects.create(nombre='Perfumes')
        cls.producto = Producto.objects.create(
            familia=familia, nombre='Yara', marca='Lattafa', precio_base=39900,
            tiene_variantes=False,
        )
        StockTienda.objects.create(tienda=cls.tienda, producto=cls.producto, cantidad=2)

    def schemas(self, response):
        parser = SchemaParser()
        parser.feed(response.content.decode())
        return parser.schemas

    def test_portada_no_declara_productos_genericos_incompletos(self):
        response = self.client.get('/')
        store = self.schemas(response)[0]
        self.assertEqual(store['@type'], 'ClothingStore')
        self.assertNotIn('makesOffer', store)
        self.assertEqual(store['url'], 'https://ideasboutique.cl/')
        self.assertContains(response, '<link rel="canonical" href="https://ideasboutique.cl/">')

    def test_producto_declara_marca_real_y_stock(self):
        with self.settings(ECOMMERCE_TIENDA_ID=self.tienda.pk):
            response = self.client.get(reverse('ecommerce:producto', args=[self.producto.pk]))
        product = self.schemas(response)[0]
        self.assertEqual(product['brand']['name'], 'Lattafa')
        self.assertEqual(product['offers']['availability'], 'https://schema.org/InStock')
        self.assertEqual(product['offers']['priceCurrency'], 'CLP')

    def test_producto_agotado_no_promete_stock(self):
        StockTienda.objects.filter(producto=self.producto).update(cantidad=0)
        with self.settings(ECOMMERCE_TIENDA_ID=self.tienda.pk):
            response = self.client.get(reverse('ecommerce:producto', args=[self.producto.pk]))
        self.assertEqual(self.schemas(response)[0]['offers']['availability'], 'https://schema.org/OutOfStock')
