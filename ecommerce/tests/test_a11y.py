"""Bloque 7: tests minimos de accesibilidad — skip link + landmarks."""
from decimal import Decimal

from django.test import TestCase, override_settings
from django.urls import reverse

from bodega.models import StockTienda, Tienda
from catalogo.models import Familia, Producto


@override_settings(ECOMMERCE_PAYMENT_GATEWAY='mock')
class A11yTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tienda = Tienda.objects.create(nombre_organizacion='Online', activa=True)
        cls.fam = Familia.objects.create(nombre='Perfumes')
        cls.producto = Producto.objects.create(
            familia=cls.fam, nombre='Yara', precio_base=Decimal('20000'),
        )
        StockTienda.objects.create(tienda=cls.tienda, producto=cls.producto, cantidad=2)

    def setUp(self):
        self.so = self.settings(ECOMMERCE_TIENDA_ID=self.tienda.pk)
        self.so.enable()

    def tearDown(self):
        self.so.disable()

    def test_skip_link_presente_en_landing(self):
        r = self.client.get(reverse('index'))
        self.assertContains(r, 'class="skip-link"')
        self.assertContains(r, 'href="#main-content"')

    def test_skip_link_target_existe_en_landing(self):
        r = self.client.get(reverse('index'))
        # El hero tiene id="main-content" tras Bloque 7.
        self.assertContains(r, 'id="main-content"')
        self.assertContains(r, 'tabindex="-1"')

    def test_skip_link_target_existe_en_catalogo(self):
        r = self.client.get(reverse('ecommerce:catalogo'))
        self.assertContains(r, 'id="main-content"')

    def test_skip_link_target_existe_en_pdp(self):
        r = self.client.get(reverse('ecommerce:producto', args=[self.producto.pk]))
        self.assertContains(r, 'id="main-content"')

    def test_skip_link_target_existe_en_carrito(self):
        r = self.client.get(reverse('ecommerce:carrito'))
        self.assertContains(r, 'id="main-content"')

    def test_toast_container_tiene_aria_live(self):
        r = self.client.get(reverse('index'))
        # El container global de toasts es para anuncios — debe ser
        # aria-live para que lectores de pantalla los anuncien.
        self.assertContains(r, 'aria-live="polite"')
