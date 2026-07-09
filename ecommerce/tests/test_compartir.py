"""Boton "Compartir" del PDP — Web Share API con fallback a copiar link."""
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from bodega.models import StockTienda, Tienda
from catalogo.models import Familia, Producto


class CompartirProductoTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.tienda = Tienda.objects.create(nombre_organizacion='Online', activa=True)
        fam = Familia.objects.create(nombre='Perfumes')
        cls.producto = Producto.objects.create(
            familia=fam, nombre='Perfume Compartible',
            precio_base=Decimal('19990'), tiene_variantes=False,
        )
        StockTienda.objects.create(tienda=cls.tienda, producto=cls.producto, cantidad=3)

    def test_pdp_tiene_boton_compartir(self):
        with self.settings(ECOMMERCE_TIENDA_ID=self.tienda.pk):
            resp = self.client.get(
                reverse('ecommerce:producto', args=[self.producto.pk]))
            self.assertContains(resp, 'id="pdp-compartir"')
            self.assertContains(resp, 'Compartir')
            # Web Share API con fallback a portapapeles.
            self.assertContains(resp, 'navigator.share')
            self.assertContains(resp, 'navigator.clipboard')
            # Icono presente en el sprite global.
            self.assertContains(resp, 'ico-share')
            # El texto compartido menciona el producto.
            self.assertContains(resp, 'Mira Perfume Compartible en Ideas Boutique')
