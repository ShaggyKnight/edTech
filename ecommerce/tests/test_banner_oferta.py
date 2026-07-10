"""Banner de campaña en el sitio público.

Cuando hay una oferta vigente online de toda la tienda o de una familia
completa, la barra de promo del header (y el tope del landing) muestran
el descuento con link a ?oferta=1. Sin campaña, la barra vuelve al
mensaje de siempre. Todo automático — cero mantención.
"""
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from bodega.models import StockTienda, Tienda
from catalogo.models import Familia, Oferta, Producto
from catalogo.precios import oferta_banner_online


@override_settings(ECOMMERCE_PAYMENT_GATEWAY='mock')
class BannerOfertaTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.tienda = Tienda.objects.create(nombre_organizacion='Online', activa=True)
        cls.perfumes = Familia.objects.create(nombre='Perfumes')
        cls.producto = Producto.objects.create(
            familia=cls.perfumes, nombre='Perfume Banner',
            precio_base=Decimal('20000'), tiene_variantes=False,
        )
        StockTienda.objects.create(tienda=cls.tienda, producto=cls.producto, cantidad=5)

    def setUp(self):
        self.settings_override = self.settings(ECOMMERCE_TIENDA_ID=self.tienda.pk)
        self.settings_override.enable()
        self.ahora = timezone.now()

    def tearDown(self):
        self.settings_override.disable()

    def _oferta(self, **kw):
        defaults = dict(
            nombre='Lanzamiento', tipo=Oferta.TIPO_PORCENTAJE,
            valor=Decimal('15'), canal=Oferta.CANAL_AMBOS,
            fecha_inicio=self.ahora - timedelta(days=1),
            fecha_fin=self.ahora + timedelta(days=10),
            activa=True,
        )
        defaults.update(kw)
        return Oferta.objects.create(**defaults)

    # ── Selector ────────────────────────────────────────────────────────

    def test_sin_ofertas_no_hay_campana(self):
        self.assertIsNone(oferta_banner_online())

    def test_oferta_puntual_no_es_campana(self):
        self._oferta(producto=self.producto)
        self.assertIsNone(oferta_banner_online())

    def test_global_es_campana(self):
        o = self._oferta()
        self.assertEqual(oferta_banner_online(), o)

    def test_global_gana_a_familia(self):
        self._oferta(nombre='Solo perfumes', familia=self.perfumes,
                     fecha_inicio=self.ahora - timedelta(hours=1))
        o_global = self._oferta(nombre='Global')
        self.assertEqual(oferta_banner_online(), o_global)

    def test_presencial_no_es_campana(self):
        self._oferta(canal=Oferta.CANAL_PRESENCIAL)
        self.assertIsNone(oferta_banner_online())

    def test_pausada_o_vencida_no_es_campana(self):
        self._oferta(activa=False)
        self._oferta(fecha_inicio=self.ahora - timedelta(days=9),
                     fecha_fin=self.ahora - timedelta(days=1))
        self.assertIsNone(oferta_banner_online())

    # ── Render en la tienda ─────────────────────────────────────────────

    def test_banner_global_en_catalogo(self):
        self._oferta(valor=Decimal('15'))
        resp = self.client.get(reverse('ecommerce:catalogo'))
        self.assertContains(resp, 'shop-promo--sale')
        self.assertContains(resp, '-15%')
        self.assertContains(resp, 'en toda la tienda')
        self.assertContains(resp, 'Ver ofertas')
        self.assertContains(resp, '?oferta=1')

    def test_banner_familia_nombra_la_familia(self):
        self._oferta(familia=self.perfumes, valor=Decimal('20'))
        resp = self.client.get(reverse('ecommerce:catalogo'))
        self.assertContains(resp, 'shop-promo--sale')
        self.assertContains(resp, '-20%')
        self.assertContains(resp, 'en Perfumes')

    def test_banner_monto_fijo_formatea_pesos(self):
        self._oferta(tipo=Oferta.TIPO_MONTO, valor=Decimal('5000'))
        resp = self.client.get(reverse('ecommerce:catalogo'))
        self.assertContains(resp, '-$5.000')

    def test_banner_muestra_fecha_de_termino(self):
        self._oferta(fecha_fin=self.ahora + timedelta(days=10))
        resp = self.client.get(reverse('ecommerce:catalogo'))
        self.assertContains(resp, 'hasta el')

    def test_sin_campana_la_barra_vuelve_al_mensaje_normal(self):
        resp = self.client.get(reverse('ecommerce:catalogo'))
        self.assertNotContains(resp, 'shop-promo--sale')
        self.assertContains(resp, 'retira gratis en tienda')

    def test_oferta_puntual_mantiene_la_barra_normal(self):
        self._oferta(producto=self.producto)
        resp = self.client.get(reverse('ecommerce:catalogo'))
        self.assertNotContains(resp, 'shop-promo--sale')

    def test_banner_tambien_en_landing(self):
        self._oferta(valor=Decimal('15'))
        resp = self.client.get(reverse('index'))
        self.assertContains(resp, 'shop-promo--sale')
        self.assertContains(resp, '-15%')

    def test_landing_sin_campana_no_muestra_banner(self):
        resp = self.client.get(reverse('index'))
        self.assertNotContains(resp, 'shop-promo--sale')
