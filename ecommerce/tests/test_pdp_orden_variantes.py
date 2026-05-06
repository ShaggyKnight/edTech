"""Orden de variantes en el detalle de producto.

Para perfumes (atributo Volumen / Concentración) tienen que aparecer
de menor a mayor tamaño (5ml → 200ml), y dentro de cada volumen por
concentración creciente (Cologne → Elixir). Para uniformes ya estaba
cubierto por el `orden_talla` — los otros atributos faltaban.
"""
from decimal import Decimal

from django.test import TestCase, override_settings
from django.urls import reverse

from bodega.models import StockTienda, Tienda
from catalogo.models import (
    Atributo, Familia, Producto, ProductoVariante, ValorAtributo,
)


@override_settings(ECOMMERCE_PAYMENT_GATEWAY='mock')
class PerfumeVariantesOrdenTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tienda = Tienda.objects.create(nombre_organizacion='Online', activa=True)
        cls.fam_perf = Familia.objects.create(nombre='Perfumes')

        cls.atr_vol = Atributo.objects.create(nombre='Volumen')
        cls.atr_conc = Atributo.objects.create(nombre='Concentración')

        # Volúmenes con `orden` ascendente — esto es lo que ordena.
        cls.v_5   = ValorAtributo.objects.create(atributo=cls.atr_vol, valor='5 ml',   orden=1)
        cls.v_30  = ValorAtributo.objects.create(atributo=cls.atr_vol, valor='30 ml',  orden=2)
        cls.v_50  = ValorAtributo.objects.create(atributo=cls.atr_vol, valor='50 ml',  orden=3)
        cls.v_100 = ValorAtributo.objects.create(atributo=cls.atr_vol, valor='100 ml', orden=4)
        cls.v_200 = ValorAtributo.objects.create(atributo=cls.atr_vol, valor='200 ml', orden=5)

        # Concentraciones — Cologne más liviano, Elixir más concentrado.
        cls.c_cologne = ValorAtributo.objects.create(atributo=cls.atr_conc, valor='Cologne',         orden=1)
        cls.c_edt     = ValorAtributo.objects.create(atributo=cls.atr_conc, valor='Eau de Toilette', orden=2)
        cls.c_edp     = ValorAtributo.objects.create(atributo=cls.atr_conc, valor='Eau de Parfum',   orden=3)
        cls.c_elixir  = ValorAtributo.objects.create(atributo=cls.atr_conc, valor='Elixir',          orden=4)

    def setUp(self):
        self.settings_override = self.settings(ECOMMERCE_TIENDA_ID=self.tienda.pk)
        self.settings_override.enable()

    def tearDown(self):
        self.settings_override.disable()

    def _crear_perfume(self, nombre):
        return Producto.objects.create(
            familia=self.fam_perf, nombre=nombre,
            precio_base=Decimal('20000'), tiene_variantes=True,
        )

    def _crear_variante(self, producto, sku, valores):
        v = ProductoVariante.objects.create(producto=producto, sku=sku)
        for val in valores:
            v.valores.add(val)
        StockTienda.objects.create(tienda=self.tienda, variante=v, cantidad=3)
        return v

    def test_perfume_solo_volumen_se_ordena_creciente(self):
        """Variantes creadas en orden 100 → 5 → 50 deben renderizarse 5 → 50 → 100."""
        p = self._crear_perfume('Yara')
        # Las creo en orden NO natural a propósito.
        self._crear_variante(p, 'YARA-100', [self.v_100])
        self._crear_variante(p, 'YARA-5',   [self.v_5])
        self._crear_variante(p, 'YARA-50',  [self.v_50])

        resp = self.client.get(reverse('ecommerce:producto', args=[p.pk]))
        self.assertEqual(resp.status_code, 200)
        skus = [v.sku for v in resp.context['variantes']]
        self.assertEqual(skus, ['YARA-5', 'YARA-50', 'YARA-100'])

    def test_perfume_volumen_y_concentracion_ordena_anidado(self):
        """Dentro de cada volumen, ordena por concentración creciente."""
        p = self._crear_perfume('Oud')
        # 30 ml Elixir + 30 ml Eau de Parfum + 100 ml Eau de Parfum.
        self._crear_variante(p, 'OUD-30-ELX', [self.v_30, self.c_elixir])
        self._crear_variante(p, 'OUD-100-EDP', [self.v_100, self.c_edp])
        self._crear_variante(p, 'OUD-30-EDP', [self.v_30, self.c_edp])

        resp = self.client.get(reverse('ecommerce:producto', args=[p.pk]))
        skus = [v.sku for v in resp.context['variantes']]
        # 30 ml EDP < 30 ml Elixir < 100 ml EDP.
        self.assertEqual(skus, ['OUD-30-EDP', 'OUD-30-ELX', 'OUD-100-EDP'])

    def test_perfume_renderiza_chips_en_orden(self):
        """Los chips del PDP aparecen en el orden correcto en el HTML."""
        p = self._crear_perfume('Floral')
        self._crear_variante(p, 'FLOR-200', [self.v_200])
        self._crear_variante(p, 'FLOR-30',  [self.v_30])
        self._crear_variante(p, 'FLOR-100', [self.v_100])

        resp = self.client.get(reverse('ecommerce:producto', args=[p.pk]))
        html = resp.content.decode()
        # El template usa data-label="30 ml" / "100 ml" / "200 ml".
        idx_30  = html.find('data-label="30 ml"')
        idx_100 = html.find('data-label="100 ml"')
        idx_200 = html.find('data-label="200 ml"')
        self.assertGreater(idx_30, 0, "data-label='30 ml' no aparece en el HTML")
        self.assertLess(idx_30, idx_100, "30 ml deberia ir antes que 100 ml")
        self.assertLess(idx_100, idx_200, "100 ml deberia ir antes que 200 ml")
