"""Tests del cálculo de precios con oferta vigente:
- Helper catalogo.precios.
- Properties precio_oferta_online / tiene_oferta_online /
  descuento_porcentaje_online en Producto y ProductoVariante.
- Render del precio con descuento en card y PDP.
"""
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from bodega.models import StockTienda, Tienda
from catalogo.barcode import generar_codigo_interno
from catalogo.models import (
    Atributo, Familia, Oferta, Producto, ProductoVariante, ValorAtributo,
)
from catalogo.precios import descuento_unitario, mejor_descuento_unitario


class PreciosHelpersTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.fam = Familia.objects.create(nombre='Perfumes')
        cls.producto = Producto.objects.create(
            familia=cls.fam, nombre='P1',
            precio_base=Decimal('20000'), tiene_variantes=False,
        )

    def _crear_oferta(self, **kw):
        defaults = dict(
            nombre='X', producto=self.producto,
            tipo=Oferta.TIPO_PORCENTAJE, valor=Decimal('20'),
            canal=Oferta.CANAL_ONLINE,
            fecha_inicio=timezone.now() - timedelta(days=1),
            fecha_fin=timezone.now() + timedelta(days=5),
            activa=True,
        )
        defaults.update(kw)
        return Oferta.objects.create(**defaults)

    def test_sin_ofertas_devuelve_cero(self):
        desc, oferta = mejor_descuento_unitario(self.producto, 'online')
        self.assertEqual(desc, Decimal('0'))
        self.assertIsNone(oferta)

    def test_oferta_porcentaje(self):
        self._crear_oferta(tipo=Oferta.TIPO_PORCENTAJE, valor=Decimal('15'))
        desc, oferta = mejor_descuento_unitario(self.producto, 'online')
        self.assertEqual(desc, Decimal('3000.00'))  # 15% de 20000
        self.assertIsNotNone(oferta)

    def test_oferta_monto_fijo(self):
        self._crear_oferta(tipo=Oferta.TIPO_MONTO, valor=Decimal('5000'))
        desc, _ = mejor_descuento_unitario(self.producto, 'online')
        self.assertEqual(desc, Decimal('5000'))

    def test_canal_solo_presencial_no_aplica_online(self):
        self._crear_oferta(canal=Oferta.CANAL_PRESENCIAL, valor=Decimal('30'))
        desc, oferta = mejor_descuento_unitario(self.producto, 'online')
        self.assertEqual(desc, Decimal('0'))
        self.assertIsNone(oferta)

    def test_pausada_no_aplica(self):
        self._crear_oferta(activa=False, valor=Decimal('30'))
        desc, _ = mejor_descuento_unitario(self.producto, 'online')
        self.assertEqual(desc, Decimal('0'))

    def test_vencida_no_aplica(self):
        ahora = timezone.now()
        self._crear_oferta(
            fecha_inicio=ahora - timedelta(days=10),
            fecha_fin=ahora - timedelta(days=1),
        )
        desc, _ = mejor_descuento_unitario(self.producto, 'online')
        self.assertEqual(desc, Decimal('0'))

    def test_mejor_de_dos_ofertas_gana(self):
        self._crear_oferta(nombre='10%', valor=Decimal('10'))
        self._crear_oferta(nombre='25%', valor=Decimal('25'))
        desc, oferta = mejor_descuento_unitario(self.producto, 'online')
        self.assertEqual(desc, Decimal('5000.00'))  # 25% de 20000
        self.assertEqual(oferta.nombre, '25%')

    def test_descuento_capeado_al_precio(self):
        """Si el monto del descuento es > que el precio, capear al precio."""
        self._crear_oferta(tipo=Oferta.TIPO_MONTO, valor=Decimal('999999'))
        desc, _ = mejor_descuento_unitario(self.producto, 'online')
        self.assertEqual(desc, Decimal('20000'))  # = precio_base

    def test_compat_descuento_unitario_wrapper(self):
        """descuento_unitario() de pos.cart sigue funcionando."""
        self._crear_oferta(valor=Decimal('10'))
        desc = descuento_unitario(self.producto, Decimal('20000'), 'online')
        self.assertEqual(desc, Decimal('2000.00'))


class ProductoPreciosOnlineTests(TestCase):
    """Properties precio_oferta_online / tiene_oferta_online / descuento_pct."""

    @classmethod
    def setUpTestData(cls):
        cls.fam = Familia.objects.create(nombre='Perfumes')
        cls.con_oferta = Producto.objects.create(
            familia=cls.fam, nombre='Con Oferta',
            precio_base=Decimal('20000'), tiene_variantes=False,
        )
        Oferta.objects.create(
            nombre='-20%', producto=cls.con_oferta,
            tipo=Oferta.TIPO_PORCENTAJE, valor=Decimal('20'),
            canal=Oferta.CANAL_AMBOS,
            fecha_inicio=timezone.now() - timedelta(days=1),
            fecha_fin=timezone.now() + timedelta(days=5),
            activa=True,
        )

        cls.sin_oferta = Producto.objects.create(
            familia=cls.fam, nombre='Sin Oferta',
            precio_base=Decimal('15000'), tiene_variantes=False,
        )

    def test_tiene_oferta_online_true(self):
        self.assertTrue(self.con_oferta.tiene_oferta_online)

    def test_tiene_oferta_online_false(self):
        self.assertFalse(self.sin_oferta.tiene_oferta_online)

    def test_precio_oferta_online_aplica_descuento(self):
        # 20000 - 20% = 16000
        self.assertEqual(self.con_oferta.precio_oferta_online, Decimal('16000.00'))

    def test_precio_oferta_online_sin_oferta_devuelve_precio_minimo(self):
        self.assertEqual(self.sin_oferta.precio_oferta_online, Decimal('15000'))

    def test_descuento_porcentaje_online(self):
        self.assertEqual(self.con_oferta.descuento_porcentaje_online, 20)
        self.assertEqual(self.sin_oferta.descuento_porcentaje_online, 0)


class ProductoConVariantesPreciosTests(TestCase):
    """BUG-003 regression guard.

    Producto con dos variantes con precios distintos y una oferta % a
    nivel producto. El "DESDE" del catálogo debe aplicar el % sobre el
    precio de cada variante y devolver el mínimo, NO restar al precio
    mínimo el descuento calculado contra `precio_base`.
    """

    @classmethod
    def setUpTestData(cls):
        cls.fam = Familia.objects.create(nombre='Perfumes')
        # precio_base = 64.990 (coincide con la variante grande, como
        # se daba en producción para Oud Royal Elixir).
        cls.producto = Producto.objects.create(
            familia=cls.fam, nombre='Oud Royal Elixir',
            precio_base=Decimal('64990'), tiene_variantes=True,
        )
        atr = Atributo.objects.create(nombre='Volumen')
        val_30 = ValorAtributo.objects.create(atributo=atr, valor='30 ml', orden=1)
        val_100 = ValorAtributo.objects.create(atributo=atr, valor='100 ml', orden=2)

        cls.v_chica = ProductoVariante.objects.create(
            producto=cls.producto, sku='OUD-30',
            precio_override=Decimal('44990'),
        )
        cls.v_chica.valores.add(val_30)

        cls.v_grande = ProductoVariante.objects.create(
            producto=cls.producto, sku='OUD-100',
            precio_override=Decimal('64990'),
        )
        cls.v_grande.valores.add(val_100)

        Oferta.objects.create(
            nombre='-10% Oud', producto=cls.producto,
            tipo=Oferta.TIPO_PORCENTAJE, valor=Decimal('10'),
            canal=Oferta.CANAL_ONLINE,
            fecha_inicio=timezone.now() - timedelta(days=1),
            fecha_fin=timezone.now() + timedelta(days=5),
            activa=True,
        )

    def test_precio_minimo_es_la_variante_barata(self):
        self.assertEqual(self.producto.precio_minimo, Decimal('44990'))

    def test_precio_oferta_online_es_la_variante_barata_con_descuento(self):
        """44.990 × 0.9 = 40.491, no 38.491."""
        self.assertEqual(
            self.producto.precio_oferta_online,
            Decimal('40491.00'),
            'BUG-003: el "DESDE" con oferta debe aplicar el % al precio '
            'mínimo de variante, no restar el descuento calculado sobre '
            '`precio_base`.',
        )

    def test_descuento_porcentaje_online_coincide_con_la_oferta(self):
        """Badge debe decir -10%, no -14% ni similar."""
        self.assertEqual(self.producto.descuento_porcentaje_online, 10)

    def test_tiene_oferta_online_true(self):
        self.assertTrue(self.producto.tiene_oferta_online)


class VariantePreciosOnlineTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.fam = Familia.objects.create(nombre='Uniformes')
        cls.producto = Producto.objects.create(
            familia=cls.fam, nombre='Buzo',
            precio_base=Decimal('30000'), tiene_variantes=True,
        )
        cls.atr = Atributo.objects.create(nombre='Talla')
        cls.val_m = ValorAtributo.objects.create(atributo=cls.atr, valor='M', orden=2)
        cls.var_m = ProductoVariante.objects.create(producto=cls.producto, sku='BZ-M')
        cls.var_m.valores.add(cls.val_m)

        Oferta.objects.create(
            nombre='-10% en la M', variante=cls.var_m,
            tipo=Oferta.TIPO_PORCENTAJE, valor=Decimal('10'),
            canal=Oferta.CANAL_ONLINE,
            fecha_inicio=timezone.now() - timedelta(days=1),
            fecha_fin=timezone.now() + timedelta(days=5),
            activa=True,
        )

    def test_variante_tiene_oferta(self):
        self.assertTrue(self.var_m.tiene_oferta_online)

    def test_variante_precio_oferta(self):
        # 30000 - 10% = 27000.
        self.assertEqual(self.var_m.precio_oferta_online, Decimal('27000.00'))


@override_settings(ECOMMERCE_PAYMENT_GATEWAY='mock')
class RenderPreciosCatalogoTests(TestCase):
    """Templates muestran el precio con descuento + tachado + badge."""

    @classmethod
    def setUpTestData(cls):
        cls.tienda = Tienda.objects.create(nombre_organizacion='Online', activa=True)
        cls.fam = Familia.objects.create(nombre='Perfumes')

        cls.producto = Producto.objects.create(
            familia=cls.fam, nombre='Yara Test',
            precio_base=Decimal('25000'), tiene_variantes=False,
        )
        cls.producto.codigo_barras = generar_codigo_interno('p', cls.producto.pk)
        cls.producto.save()
        StockTienda.objects.create(tienda=cls.tienda, producto=cls.producto, cantidad=5)

        Oferta.objects.create(
            nombre='-20%', producto=cls.producto,
            tipo=Oferta.TIPO_PORCENTAJE, valor=Decimal('20'),
            canal=Oferta.CANAL_AMBOS,
            fecha_inicio=timezone.now() - timedelta(days=1),
            fecha_fin=timezone.now() + timedelta(days=5),
            activa=True,
        )

    def setUp(self):
        self.settings_override = self.settings(ECOMMERCE_TIENDA_ID=self.tienda.pk)
        self.settings_override.enable()

    def tearDown(self):
        self.settings_override.disable()

    def test_card_muestra_precio_con_descuento_y_tachado(self):
        resp = self.client.get(reverse('ecommerce:catalogo'))
        body = resp.content.decode()
        # Precio nuevo (20000 con descuento) en vino + el original tachado
        # (25000). Sin badge.
        self.assertIn('20.000', body)        # precio con descuento (locale)
        self.assertIn('pcard-price-sale', body)
        self.assertIn('pcard-old', body)
        self.assertNotIn('pcard-discount-badge', body)

    def test_pdp_muestra_precio_con_descuento_y_tachado(self):
        resp = self.client.get(reverse('ecommerce:producto', args=[self.producto.pk]))
        body = resp.content.decode()
        self.assertIn('pdp-price-sale', body)
        self.assertIn('pdp-price-old', body)
        self.assertNotIn('pdp-price-badge', body)
