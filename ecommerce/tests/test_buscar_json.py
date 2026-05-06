"""Tests del endpoint live search /tienda/buscar.json."""
import json
from decimal import Decimal

from django.test import TestCase, override_settings
from django.urls import reverse

from bodega.models import StockTienda, Tienda
from catalogo.models import Colegio, Familia, Producto


@override_settings(ECOMMERCE_PAYMENT_GATEWAY='mock')
class BuscarJsonTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tienda = Tienda.objects.create(nombre_organizacion='Online', activa=True)
        cls.fam_unif = Familia.objects.create(nombre='Uniformes')
        cls.fam_perf = Familia.objects.create(nombre='Perfumes')
        cls.sfj = Colegio.objects.create(nombre='San Francisco Javier')
        cls.dp = Colegio.objects.create(nombre='Divina Providencia')

        cls.buzo = Producto.objects.create(
            familia=cls.fam_unif, colegio=cls.sfj,
            nombre='Buzo SFJ Completo',
            descripcion='Tela franela silvia',
            precio_base=Decimal('25000'), tiene_variantes=False,
        )
        StockTienda.objects.create(tienda=cls.tienda, producto=cls.buzo, cantidad=5)

        cls.perfume = Producto.objects.create(
            familia=cls.fam_perf, nombre='Perfume Avéllá',
            descripcion='Cítricos frescos',
            precio_base=Decimal('30000'), tiene_variantes=False,
        )
        StockTienda.objects.create(tienda=cls.tienda, producto=cls.perfume, cantidad=2)

        # Producto sin stock — no debe aparecer.
        cls.agotado = Producto.objects.create(
            familia=cls.fam_unif, colegio=cls.sfj, nombre='Buzo SFJ Agotado',
            precio_base=Decimal('25000'), tiene_variantes=False,
        )
        StockTienda.objects.create(tienda=cls.tienda, producto=cls.agotado, cantidad=0)

    def setUp(self):
        self.settings_override = self.settings(ECOMMERCE_TIENDA_ID=self.tienda.pk)
        self.settings_override.enable()

    def tearDown(self):
        self.settings_override.disable()

    def _get(self, q):
        resp = self.client.get(reverse('ecommerce:buscar_json') + f'?q={q}')
        self.assertEqual(resp.status_code, 200)
        return json.loads(resp.content)

    def test_query_corto_devuelve_vacio(self):
        data = self._get('b')
        self.assertEqual(data, {'productos': [], 'colegios': []})

    def test_busqueda_basica_encuentra_productos(self):
        data = self._get('buzo')
        nombres = [p['nombre'] for p in data['productos']]
        self.assertIn('Buzo SFJ Completo', nombres)
        # No incluye el agotado (sin stock).
        self.assertNotIn('Buzo SFJ Agotado', nombres)

    def test_accent_insensitive(self):
        # "perfume avella" sin acentos debe encontrar "Perfume Avéllá".
        data = self._get('avella')
        nombres = [p['nombre'] for p in data['productos']]
        self.assertIn('Perfume Avéllá', nombres)

    def test_case_insensitive(self):
        data = self._get('PERFUME')
        nombres = [p['nombre'] for p in data['productos']]
        self.assertIn('Perfume Avéllá', nombres)

    def test_busqueda_en_descripcion(self):
        data = self._get('citricos')
        nombres = [p['nombre'] for p in data['productos']]
        self.assertIn('Perfume Avéllá', nombres)

    def test_colegios_sugieren_filtro(self):
        data = self._get('san franc')
        nombres_col = [c['nombre'] for c in data['colegios']]
        self.assertIn('San Francisco Javier', nombres_col)
        # El colegio incluye URL al filtro.
        sfj = data['colegios'][0]
        self.assertIn(f'colegio={self.sfj.pk}', sfj['url'])

    def test_estructura_producto(self):
        data = self._get('buzo')
        p = next(x for x in data['productos'] if x['nombre'] == 'Buzo SFJ Completo')
        # Campos esperados por el JS.
        self.assertEqual(p['categoria'], 'Uniformes')
        self.assertEqual(p['colegio'], 'San Francisco Javier')
        self.assertEqual(p['precio'], 25000.0)
        self.assertIn('/tienda/p/', p['url'])
        self.assertTrue(p['img'])  # tiene URL de imagen (default svg si no hay)
