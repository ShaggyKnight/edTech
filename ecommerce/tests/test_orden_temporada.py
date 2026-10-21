"""Temporada escolar: el orden "Más relevantes" pone primero los uniformes.

Entre diciembre y marzo (settings.TEMPORADA_UNIFORMES_MESES) los
apoderados vienen por uniformes; el resto del año el orden no cambia.
"""
from datetime import date
from decimal import Decimal
from unittest import mock

from django.test import TestCase, override_settings
from django.urls import reverse

from bodega.models import StockTienda, Tienda
from catalogo.models import Familia, Producto
from ecommerce.categorias import categoria_de_temporada

ENERO = date(2027, 1, 15)
OCTUBRE = date(2026, 10, 21)


def en_fecha(dia):
    return mock.patch('django.utils.timezone.localdate', return_value=dia)


class CategoriaDeTemporadaTests(TestCase):

    @override_settings(TEMPORADA_UNIFORMES_MESES=[12, 1, 2, 3])
    def test_meses_de_temporada(self):
        self.assertEqual(categoria_de_temporada(date(2026, 12, 1)), 'uniformes')
        self.assertEqual(categoria_de_temporada(date(2027, 3, 31)), 'uniformes')
        self.assertIsNone(categoria_de_temporada(date(2027, 4, 1)))
        self.assertIsNone(categoria_de_temporada(OCTUBRE))

    @override_settings(TEMPORADA_UNIFORMES_MESES=[])
    def test_sin_meses_nunca_hay_temporada(self):
        self.assertIsNone(categoria_de_temporada(ENERO))


@override_settings(TEMPORADA_UNIFORMES_MESES=[12, 1, 2, 3])
class OrdenTemporadaTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.tienda = Tienda.objects.create(nombre_organizacion='Online', activa=True)
        perfumes = Familia.objects.create(nombre='Perfumes')
        uniformes = Familia.objects.create(nombre='Uniformes Escolares')
        cls.perfume = Producto.objects.create(
            familia=perfumes, nombre='Aaa Perfume',
            precio_base=Decimal('30000'), tiene_variantes=False,
            imagen='productos/perfume.jpg',
        )
        cls.buzo = Producto.objects.create(
            familia=uniformes, nombre='Buzo Colegio',
            precio_base=Decimal('20000'), tiene_variantes=False,
            imagen='productos/buzo.jpg',
        )
        cls.chaleco = Producto.objects.create(
            familia=uniformes, nombre='Chaleco Sin Foto',
            precio_base=Decimal('15000'), tiene_variantes=False,
        )
        for p in (cls.perfume, cls.buzo, cls.chaleco):
            StockTienda.objects.create(tienda=cls.tienda, producto=p, cantidad=3)

    def nombres(self, query=''):
        with self.settings(ECOMMERCE_TIENDA_ID=self.tienda.pk):
            resp = self.client.get(reverse('ecommerce:catalogo') + query)
        return [p.nombre for p in resp.context['productos']]

    def test_en_temporada_uniformes_primero(self):
        with en_fecha(ENERO):
            nombres = self.nombres()
        # Uniforme con foto, uniforme sin foto, y recien ahi el perfume.
        self.assertEqual(nombres, ['Buzo Colegio', 'Chaleco Sin Foto', 'Aaa Perfume'])

    def test_fuera_de_temporada_orden_de_siempre(self):
        with en_fecha(OCTUBRE):
            nombres = self.nombres()
        self.assertEqual(nombres, ['Aaa Perfume', 'Buzo Colegio', 'Chaleco Sin Foto'])

    def test_orden_elegido_por_el_cliente_se_respeta(self):
        with en_fecha(ENERO):
            nombres = self.nombres('?sort=high')
        self.assertEqual(nombres, ['Aaa Perfume', 'Buzo Colegio', 'Chaleco Sin Foto'])
