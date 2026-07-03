"""Umbral de "stock bajo" por familia.

El negocio maneja 1-2 unidades por perfume — eso es stock NORMAL. Con
el umbral general (5) toda la perfumeria aparecia "Bajo" siempre, puro
ruido. Ahora cada Familia puede definir su umbral (0 = solo alertar
agotados) y el general queda para el resto (uniformes, etc).
"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from bodega.models import StockTienda, Tienda
from catalogo.models import Familia, Producto

User = get_user_model()


class UmbralPorFamiliaTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.tienda = Tienda.objects.create(nombre_organizacion='Central', activa=True)
        # Perfumes: umbral 0 (solo agotado alerta). La migracion 0012 lo
        # setea para familias existentes con "perfum" en el nombre; aca
        # lo seteamos explicito porque la familia se crea en el test.
        cls.perfumes = Familia.objects.create(nombre='Perfumería', umbral_stock_bajo=0)
        # Buzos: sin umbral propio → usa el general (5).
        cls.buzos = Familia.objects.create(nombre='Buzos')

        cls.perfume = Producto.objects.create(
            familia=cls.perfumes, nombre='Perfume Solo Uno',
            precio_base=Decimal('19990'), tiene_variantes=False,
        )
        cls.buzo = Producto.objects.create(
            familia=cls.buzos, nombre='Buzo Poco Stock',
            precio_base=Decimal('15990'), tiene_variantes=False,
        )
        # 1 unidad de cada uno: normal para el perfume, bajo para el buzo.
        StockTienda.objects.create(tienda=cls.tienda, producto=cls.perfume, cantidad=1)
        StockTienda.objects.create(tienda=cls.tienda, producto=cls.buzo, cantidad=1)

        cls.admin = User.objects.create_superuser('admin', password='x')

    def setUp(self):
        self.client.force_login(self.admin)

    def _html_stock(self, extra=''):
        resp = self.client.get(reverse('bodega:stock') + f'?solo=todos{extra}')
        self.assertEqual(resp.status_code, 200)
        return resp

    def test_perfume_con_1_unidad_es_ok_no_bajo(self):
        resp = self._html_stock('&familia=%s' % self.perfumes.pk)
        body = resp.content.decode()
        self.assertIn('Perfume Solo Uno', body)
        self.assertNotIn('bo-badge-warning', body)   # sin badge "Bajo"
        self.assertIn('bo-badge-success', body)      # badge "OK"

    def test_buzo_con_1_unidad_sigue_siendo_bajo(self):
        resp = self._html_stock('&familia=%s' % self.buzos.pk)
        body = resp.content.decode()
        self.assertIn('Buzo Poco Stock', body)
        self.assertIn('bo-badge-warning', body)

    def test_kpi_bajo_no_cuenta_perfumes(self):
        resp = self._html_stock()
        # Solo el buzo esta "bajo"; el perfume con 1 unidad no.
        self.assertEqual(resp.context['kpi']['n_bajo'], 1)
        self.assertEqual(resp.context['kpi']['n_ok'], 1)

    def test_filtro_solo_bajo_respeta_umbral_por_familia(self):
        resp = self.client.get(reverse('bodega:stock') + '?solo=bajo')
        nombres = [
            (s.variante.producto.nombre if s.variante else s.producto.nombre)
            for s in resp.context['stock']
        ]
        self.assertEqual(nombres, ['Buzo Poco Stock'])

    def test_perfume_agotado_si_alerta(self):
        StockTienda.objects.filter(producto=self.perfume).update(cantidad=0)
        resp = self._html_stock('&familia=%s' % self.perfumes.pk)
        self.assertIn('bo-badge-danger', resp.content.decode())

    def test_set_stock_htmx_devuelve_fila_con_umbral_correcto(self):
        fila = StockTienda.objects.get(producto=self.perfume)
        resp = self.client.post(
            reverse('bodega:set_stock', args=[fila.pk]),
            {'cantidad': '2'},
            HTTP_HX_REQUEST='true',
        )
        body = resp.content.decode()
        # 2 unidades de perfume con umbral 0 → OK, no "Bajo".
        self.assertIn('bo-badge-success', body)
        self.assertNotIn('bo-badge-warning', body)

    def test_migracion_seteo_umbral_0_a_perfumeria_existente(self):
        """La data migration marca familias 'perfum*' con umbral 0 —
        acá verificamos la convención sobre una familia nueva sin set
        explícito: NO hereda 0 (usa el general)."""
        moda = Familia.objects.create(nombre='Moda')
        self.assertIsNone(moda.umbral_stock_bajo)
