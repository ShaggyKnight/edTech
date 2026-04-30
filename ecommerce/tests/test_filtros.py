"""Tests de filtros y búsqueda accent-insensitive en el catálogo público."""
from decimal import Decimal

from django.test import TestCase, override_settings
from django.urls import reverse

from bodega.models import StockTienda, Tienda
from catalogo.models import (
    Atributo, Colegio, Familia, Producto, ProductoVariante, ValorAtributo,
)


@override_settings(ECOMMERCE_PAYMENT_GATEWAY='mock')
class CatalogoFiltrosTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tienda = Tienda.objects.create(nombre_organizacion='Online', activa=True)
        cls.fam_unif = Familia.objects.create(nombre='Uniformes')
        cls.fam_perf = Familia.objects.create(nombre='Perfumes')

        cls.sfj = Colegio.objects.create(nombre='SFJ')
        cls.dp = Colegio.objects.create(nombre='Divina Providencia')

        cls.atr = Atributo.objects.create(nombre='Talla')
        cls.val_m = ValorAtributo.objects.create(atributo=cls.atr, valor='M')
        cls.val_l = ValorAtributo.objects.create(atributo=cls.atr, valor='L')
        cls.val_xl = ValorAtributo.objects.create(atributo=cls.atr, valor='XL')

        # Buzo SFJ con tallas M (con stock) y XL (sin stock).
        cls.buzo_sfj = Producto.objects.create(
            familia=cls.fam_unif, colegio=cls.sfj,
            nombre='Buzo SFJ',
            precio_base=Decimal('30000'),
            tiene_variantes=True,
        )
        v_m = ProductoVariante.objects.create(producto=cls.buzo_sfj, sku='BZ-M')
        v_m.valores.add(cls.val_m)
        StockTienda.objects.create(tienda=cls.tienda, variante=v_m, cantidad=5)

        v_xl = ProductoVariante.objects.create(producto=cls.buzo_sfj, sku='BZ-XL')
        v_xl.valores.add(cls.val_xl)
        StockTienda.objects.create(tienda=cls.tienda, variante=v_xl, cantidad=0)

        # Polera DP solo en talla L con stock.
        cls.polera_dp = Producto.objects.create(
            familia=cls.fam_unif, colegio=cls.dp,
            nombre='Polera DP',
            precio_base=Decimal('12000'),
            tiene_variantes=True,
        )
        v_l = ProductoVariante.objects.create(producto=cls.polera_dp, sku='PDP-L')
        v_l.valores.add(cls.val_l)
        StockTienda.objects.create(tienda=cls.tienda, variante=v_l, cantidad=3)

        # Perfume sin colegio, sin variantes, con stock directo.
        cls.perfume = Producto.objects.create(
            familia=cls.fam_perf, nombre='Perfume Avéllá',
            descripcion='Notas frescas de cítricos',
            precio_base=Decimal('50000'),
            tiene_variantes=False,
        )
        StockTienda.objects.create(tienda=cls.tienda, producto=cls.perfume, cantidad=4)

    def setUp(self):
        # Setea ECOMMERCE_TIENDA_ID al pk de la tienda creada para que los
        # tests no dependan del .env.
        self.settings_override = self.settings(ECOMMERCE_TIENDA_ID=self.tienda.pk)
        self.settings_override.enable()

    def tearDown(self):
        self.settings_override.disable()

    def test_filtro_colegio_sfj(self):
        resp = self.client.get(reverse('ecommerce:catalogo') + f'?colegio={self.sfj.pk}')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Buzo SFJ')
        self.assertNotContains(resp, 'Polera DP')
        self.assertNotContains(resp, 'Perfume Av')

    def test_filtro_colegio_dp(self):
        resp = self.client.get(reverse('ecommerce:catalogo') + f'?colegio={self.dp.pk}')
        self.assertContains(resp, 'Polera DP')
        self.assertNotContains(resp, 'Buzo SFJ')

    def test_filtro_talla_m(self):
        resp = self.client.get(reverse('ecommerce:catalogo') + '?talla=M')
        self.assertContains(resp, 'Buzo SFJ')      # tiene M con stock
        self.assertNotContains(resp, 'Polera DP')  # solo L

    def test_filtro_talla_xl_oculta_buzo_sin_stock(self):
        resp = self.client.get(reverse('ecommerce:catalogo') + '?talla=XL')
        # XL existe en Buzo pero stock=0 → no debe aparecer.
        self.assertNotContains(resp, 'Buzo SFJ')

    def test_filtro_precio_max(self):
        resp = self.client.get(reverse('ecommerce:catalogo') + '?precio_max=20000')
        # Solo Polera DP ($12k); Buzo ($30k) y Perfume ($50k) afuera.
        self.assertContains(resp, 'Polera DP')
        self.assertNotContains(resp, 'Buzo SFJ')

    def test_filtro_precio_min(self):
        resp = self.client.get(reverse('ecommerce:catalogo') + '?precio_min=40000')
        self.assertContains(resp, 'Perfume')
        self.assertNotContains(resp, 'Polera DP')
        self.assertNotContains(resp, 'Buzo SFJ')

    def test_busqueda_sin_acentos(self):
        # Buscar "perfume avella" debe encontrar "Perfume Avéllá".
        resp = self.client.get(reverse('ecommerce:catalogo') + '?q=avella')
        self.assertContains(resp, 'Perfume Av')

    def test_busqueda_con_acentos(self):
        resp = self.client.get(reverse('ecommerce:catalogo') + '?q=avéllá')
        self.assertContains(resp, 'Perfume Av')

    def test_busqueda_mayusculas(self):
        resp = self.client.get(reverse('ecommerce:catalogo') + '?q=PERFUME')
        self.assertContains(resp, 'Perfume Av')

    def test_busqueda_en_descripcion(self):
        resp = self.client.get(reverse('ecommerce:catalogo') + '?q=citricos')
        self.assertContains(resp, 'Perfume Av')

    def test_filtros_combinados(self):
        # Colegio SFJ + talla M.
        resp = self.client.get(
            reverse('ecommerce:catalogo')
            + f'?colegio={self.sfj.pk}&talla=M'
        )
        self.assertContains(resp, 'Buzo SFJ')
        self.assertNotContains(resp, 'Polera DP')

    def test_tallas_disponibles_en_contexto(self):
        resp = self.client.get(reverse('ecommerce:catalogo'))
        # Solo M y L tienen stock — XL no debe aparecer en tallas_disponibles.
        tallas = list(resp.context['tallas_disponibles'])
        self.assertIn('M', tallas)
        self.assertIn('L', tallas)
        self.assertNotIn('XL', tallas)
