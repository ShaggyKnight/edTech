"""Tests de categorias visibles segun stock online.

Una categoria aparece en el menu, la landing, el pie y el sitemap solo
si tiene al menos un producto activo con stock en la tienda online. Sin
stock, desaparece de todos lados y su pagina queda con `noindex`.
"""

from decimal import Decimal

from django.test import TestCase, override_settings
from django.urls import reverse

from bodega.models import StockTienda, Tienda
from catalogo.models import Familia, Producto
from ecommerce.categorias import categorias_visibles, slugs_con_stock


@override_settings(ECOMMERCE_PAYMENT_GATEWAY='mock')
class CategoriasVisiblesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tienda = Tienda.objects.create(nombre_organizacion='T', activa=True)
        cls.fam_uniformes = Familia.objects.create(nombre='Uniformes Escolares')
        cls.fam_perfumes = Familia.objects.create(nombre='Perfumes')
        cls.fam_moda = Familia.objects.create(nombre='Moda')
        cls.fam_intima = Familia.objects.create(nombre='Lencería')

        cls.uniforme = Producto.objects.create(
            familia=cls.fam_uniformes, nombre='Buzo Cole',
            precio_base=Decimal('25000'), tiene_variantes=False,
        )
        cls.perfume = Producto.objects.create(
            familia=cls.fam_perfumes, nombre='Eau de Toilette',
            precio_base=Decimal('45000'), tiene_variantes=False,
        )
        # Moda: producto cargado pero sin stock. Intima: sin productos.
        cls.polera = Producto.objects.create(
            familia=cls.fam_moda, nombre='Polera lino',
            precio_base=Decimal('15000'), tiene_variantes=False,
        )
        StockTienda.objects.create(tienda=cls.tienda, producto=cls.uniforme, cantidad=5)
        StockTienda.objects.create(tienda=cls.tienda, producto=cls.perfume, cantidad=2)
        StockTienda.objects.create(tienda=cls.tienda, producto=cls.polera, cantidad=0)

    def get(self, url):
        with self.settings(ECOMMERCE_TIENDA_ID=self.tienda.pk):
            return self.client.get(url)

    def test_solo_categorias_con_stock(self):
        self.assertEqual(slugs_con_stock(self.tienda), ['uniformes', 'perfumes'])

    def test_aparece_al_llegar_stock(self):
        StockTienda.objects.filter(producto=self.polera).update(cantidad=3)
        self.assertEqual(
            slugs_con_stock(self.tienda), ['uniformes', 'perfumes', 'moda'],
        )

    def test_producto_inactivo_no_cuenta(self):
        Producto.objects.filter(pk=self.perfume.pk).update(activo=False)
        self.assertEqual(slugs_con_stock(self.tienda), ['uniformes'])

    def test_sin_tienda_configurada_no_hay_categorias(self):
        with self.settings(ECOMMERCE_TIENDA_ID=None):
            self.assertEqual(categorias_visibles(), [])

    def test_categorias_visibles_trae_datos_del_menu(self):
        cats = categorias_visibles(self.tienda)
        self.assertEqual(cats[0]['slug'], 'uniformes')
        self.assertEqual(cats[0]['nav'], 'Uniformes')
        self.assertNotIn('match', cats[0])

    def test_menu_de_la_tienda_oculta_categorias_sin_stock(self):
        resp = self.get(reverse('ecommerce:catalogo'))
        self.assertContains(resp, '?cat=uniformes')
        self.assertContains(resp, '?cat=perfumes')
        self.assertNotContains(resp, '?cat=moda')
        self.assertNotContains(resp, '?cat=intima')

    def test_filtro_lateral_solo_con_stock(self):
        resp = self.get(reverse('ecommerce:catalogo'))
        slugs = [c['slug'] for c in resp.context['categorias']]
        self.assertEqual(slugs, ['uniformes', 'perfumes'])

    def test_categoria_sin_stock_mensaje_y_noindex(self):
        resp = self.get(reverse('ecommerce:catalogo') + '?cat=moda')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.context['cat_sin_stock'])
        self.assertContains(resp, 'Por ahora no tenemos moda en la tienda online')
        self.assertContains(resp, '<meta name="robots" content="noindex, follow">', html=True)
        # La activa se sigue ofreciendo en el filtro para poder salir de ella.
        slugs = [c['slug'] for c in resp.context['categorias']]
        self.assertIn('moda', slugs)

    def test_categoria_con_stock_se_indexa(self):
        resp = self.get(reverse('ecommerce:catalogo') + '?cat=uniformes')
        self.assertFalse(resp.context['cat_sin_stock'])
        self.assertNotContains(resp, 'noindex')

    def test_landing_muestra_solo_tarjetas_con_stock(self):
        resp = self.get(reverse('index'))
        self.assertContains(resp, 'Dos mundos, una sola tienda.')
        self.assertContains(resp, 'cats-grid--2')
        self.assertNotContains(resp, '?cat=moda')
        self.assertNotContains(resp, '?cat=intima')

    def test_sitemap_solo_categorias_con_stock(self):
        resp = self.get('/sitemap.xml')
        self.assertContains(resp, 'cat=uniformes')
        self.assertNotContains(resp, 'cat=moda')
        self.assertNotContains(resp, 'cat=intima')
