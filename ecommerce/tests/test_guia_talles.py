"""Bloque 12: tests de la guia/calculadora de talles en el PDP."""
from decimal import Decimal

from django.test import TestCase, override_settings
from django.urls import reverse

from bodega.models import StockTienda, Tienda
from catalogo.models import (
    Atributo, Familia, Producto, ProductoVariante, ValorAtributo,
)


@override_settings(ECOMMERCE_PAYMENT_GATEWAY='mock')
class GuiaTallesPDPTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tienda = Tienda.objects.create(nombre_organizacion='Online', activa=True)

        # Producto con atributo Talla — debe mostrar la guia.
        cls.fam_uni = Familia.objects.create(nombre='Buzos')
        cls.uniforme = Producto.objects.create(
            familia=cls.fam_uni, nombre='Buzo SFJ',
            precio_base=Decimal('20000'), tiene_variantes=True,
        )
        atr_talla = Atributo.objects.create(nombre='Talla')
        val_10 = ValorAtributo.objects.create(atributo=atr_talla, valor='10', orden=4)
        v = ProductoVariante.objects.create(producto=cls.uniforme, sku='BZ-10')
        v.valores.add(val_10)
        StockTienda.objects.create(tienda=cls.tienda, variante=v, cantidad=3)

        # Producto con atributo Volumen (perfume) — NO debe mostrar la guia.
        cls.fam_perf = Familia.objects.create(nombre='Perfumes')
        cls.perfume = Producto.objects.create(
            familia=cls.fam_perf, nombre='Yara EDP',
            precio_base=Decimal('30000'), tiene_variantes=True,
        )
        atr_vol = Atributo.objects.create(nombre='Volumen')
        val_100 = ValorAtributo.objects.create(atributo=atr_vol, valor='100 ml', orden=1)
        vp = ProductoVariante.objects.create(producto=cls.perfume, sku='YA-100')
        vp.valores.add(val_100)
        StockTienda.objects.create(tienda=cls.tienda, variante=vp, cantidad=2)

        # Producto sin variantes — NO debe mostrar la guia.
        cls.simple = Producto.objects.create(
            familia=cls.fam_perf, nombre='Simple',
            precio_base=Decimal('10000'), tiene_variantes=False,
        )
        StockTienda.objects.create(tienda=cls.tienda, producto=cls.simple, cantidad=5)

    def setUp(self):
        self.so = self.settings(ECOMMERCE_TIENDA_ID=self.tienda.pk)
        self.so.enable()

    def tearDown(self):
        self.so.disable()

    def test_pdp_uniforme_muestra_boton_guia(self):
        r = self.client.get(reverse('ecommerce:producto', args=[self.uniforme.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Guía de talles')
        self.assertContains(r, 'pdp-guia-link')
        # El modal viene cargado en el HTML.
        self.assertContains(r, 'id="guia-talles-modal"')

    def test_pdp_perfume_no_muestra_boton_guia(self):
        """Perfume tiene atributo Volumen, no Talla — sin guia."""
        r = self.client.get(reverse('ecommerce:producto', args=[self.perfume.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, 'pdp-guia-link')
        self.assertNotContains(r, 'id="guia-talles-modal"')

    def test_pdp_producto_simple_no_muestra_boton_guia(self):
        """Producto sin variantes — sin guia."""
        r = self.client.get(reverse('ecommerce:producto', args=[self.simple.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, 'pdp-guia-link')

    def test_guia_incluye_tabla_y_calculadora(self):
        r = self.client.get(reverse('ecommerce:producto', args=[self.uniforme.pk]))
        # Tabs.
        self.assertContains(r, 'Tabla de medidas')
        self.assertContains(r, 'Calculadora rápida')
        # Algunas tallas estandar en la tabla.
        self.assertContains(r, '>4<')
        self.assertContains(r, '>10<')
        self.assertContains(r, '>XXL<')
        # Inputs de la calculadora.
        self.assertContains(r, 'id="calc-edad"')
        self.assertContains(r, 'id="calc-altura"')
        self.assertContains(r, 'id="calc-pecho"')
