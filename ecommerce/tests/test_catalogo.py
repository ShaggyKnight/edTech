"""Tests del catálogo público con filtros por familia y por slug de categoría.

Cubre el mapeo CAT_SLUGS introducido en Fase G y el comportamiento de las
vistas de catálogo y detalle bajo distintos estados de stock.
"""

from decimal import Decimal

from django.test import TestCase, override_settings
from django.urls import reverse

from bodega.models import StockTienda, Tienda
from catalogo.models import Familia, Producto


@override_settings(ECOMMERCE_PAYMENT_GATEWAY='mock')
class CatalogoFiltrosTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tienda = Tienda.objects.create(nombre_organizacion='T', activa=True)
        cls.fam_uniformes = Familia.objects.create(nombre='Uniformes Escolares')
        cls.fam_perfumes = Familia.objects.create(nombre='Perfumes')
        cls.fam_intima = Familia.objects.create(nombre='Lencería')

        cls.uniforme = Producto.objects.create(
            familia=cls.fam_uniformes, nombre='Buzo Cole',
            precio_base=Decimal('25000'), tiene_variantes=False,
        )
        cls.perfume = Producto.objects.create(
            familia=cls.fam_perfumes, nombre='Eau de Toilette',
            precio_base=Decimal('45000'), tiene_variantes=False,
        )
        cls.calzon = Producto.objects.create(
            familia=cls.fam_intima, nombre='Calzón básico',
            precio_base=Decimal('5000'), tiene_variantes=False,
        )
        # Todos con stock para que aparezcan en el catálogo.
        for p in (cls.uniforme, cls.perfume, cls.calzon):
            StockTienda.objects.create(tienda=cls.tienda, producto=p, cantidad=5)

    def test_sin_filtro_lista_todos(self):
        with self.settings(ECOMMERCE_TIENDA_ID=self.tienda.pk):
            resp = self.client.get(reverse('ecommerce:catalogo'))
            self.assertEqual(resp.status_code, 200)
            self.assertContains(resp, 'Buzo Cole')
            self.assertContains(resp, 'Eau de Toilette')
            self.assertContains(resp, 'Calzón básico')

    def test_filtro_cat_uniformes_solo_uniformes(self):
        with self.settings(ECOMMERCE_TIENDA_ID=self.tienda.pk):
            resp = self.client.get(reverse('ecommerce:catalogo') + '?cat=uniformes')
            self.assertEqual(resp.status_code, 200)
            self.assertContains(resp, 'Buzo Cole')
            self.assertNotContains(resp, 'Eau de Toilette')
            self.assertNotContains(resp, 'Calzón básico')
            # El header de categoría debe traer el accent vino.
            self.assertEqual(resp.context['cat_activa'], 'uniformes')
            self.assertEqual(resp.context['cat_info']['accent'], '#7A1E2B')

    def test_filtro_cat_perfumes_match_por_icontains(self):
        """`fragranc` y `perfum` ambos hacen match para slug `perfumes`."""
        fam_frag = Familia.objects.create(nombre='Fragancias premium')
        decant = Producto.objects.create(
            familia=fam_frag, nombre='Decant 5ml',
            precio_base=Decimal('8000'), tiene_variantes=False,
        )
        StockTienda.objects.create(tienda=self.tienda, producto=decant, cantidad=3)

        with self.settings(ECOMMERCE_TIENDA_ID=self.tienda.pk):
            resp = self.client.get(reverse('ecommerce:catalogo') + '?cat=perfumes')
            self.assertContains(resp, 'Eau de Toilette')
            self.assertContains(resp, 'Decant 5ml')

    def test_filtro_cat_intima(self):
        with self.settings(ECOMMERCE_TIENDA_ID=self.tienda.pk):
            resp = self.client.get(reverse('ecommerce:catalogo') + '?cat=intima')
            self.assertContains(resp, 'Calzón básico')
            self.assertNotContains(resp, 'Buzo Cole')

    def test_filtro_cat_invalido_no_filtra(self):
        with self.settings(ECOMMERCE_TIENDA_ID=self.tienda.pk):
            resp = self.client.get(reverse('ecommerce:catalogo') + '?cat=fuera-de-mapa')
            # Slug desconocido: no filtra y no marca categoría activa.
            self.assertEqual(resp.context['cat_activa'], '')
            self.assertIsNone(resp.context['cat_info'])
            self.assertContains(resp, 'Buzo Cole')

    def test_query_q_filtra_por_nombre(self):
        with self.settings(ECOMMERCE_TIENDA_ID=self.tienda.pk):
            resp = self.client.get(reverse('ecommerce:catalogo') + '?q=Buzo')
            self.assertContains(resp, 'Buzo Cole')
            self.assertNotContains(resp, 'Eau de Toilette')

    def test_producto_sin_stock_no_aparece(self):
        """Si todo el stock es 0, el producto desaparece del listado."""
        StockTienda.objects.filter(producto=self.calzon).update(cantidad=0)
        with self.settings(ECOMMERCE_TIENDA_ID=self.tienda.pk):
            resp = self.client.get(reverse('ecommerce:catalogo'))
            self.assertNotContains(resp, 'Calzón básico')


@override_settings(ECOMMERCE_PAYMENT_GATEWAY='mock')
class TiendaSinConfigurarTests(TestCase):
    def test_503_si_falta_ecommerce_tienda_id(self):
        with self.settings(ECOMMERCE_TIENDA_ID=None):
            resp = self.client.get(reverse('ecommerce:catalogo'))
            self.assertEqual(resp.status_code, 503)
            self.assertContains(resp, 'mantención', status_code=503)

    def test_503_si_tienda_inactiva(self):
        Tienda.objects.create(nombre_organizacion='Apagada', activa=False, pk=99)
        with self.settings(ECOMMERCE_TIENDA_ID=99):
            resp = self.client.get(reverse('ecommerce:catalogo'))
            self.assertEqual(resp.status_code, 503)
