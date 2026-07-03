"""El orden 'relevante' del catalogo manda los productos sin foto al final."""
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from bodega.models import StockTienda, Tienda
from catalogo.models import Familia, Producto


class OrdenSinFotoTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.tienda = Tienda.objects.create(nombre_organizacion='Online', activa=True)
        fam = Familia.objects.create(nombre='Perfumes')
        # "AAA Sin Foto" ordenaria PRIMERO alfabeticamente — el test
        # verifica que la falta de foto pese mas que el nombre.
        cls.sin_foto = Producto.objects.create(
            familia=fam, nombre='AAA Sin Foto',
            precio_base=Decimal('10000'), tiene_variantes=False,
        )
        cls.con_foto = Producto.objects.create(
            familia=fam, nombre='ZZZ Con Foto',
            precio_base=Decimal('10000'), tiene_variantes=False,
            imagen='productos/zzz.jpg',
        )
        for p in (cls.sin_foto, cls.con_foto):
            StockTienda.objects.create(tienda=cls.tienda, producto=p, cantidad=3)

    def setUp(self):
        self.override = self.settings(ECOMMERCE_TIENDA_ID=self.tienda.pk)
        self.override.enable()

    def tearDown(self):
        self.override.disable()

    def test_relevante_pone_sin_foto_al_final(self):
        resp = self.client.get(reverse('ecommerce:catalogo'))
        body = resp.content.decode()
        self.assertLess(
            body.index('ZZZ Con Foto'), body.index('AAA Sin Foto'),
            'El producto sin foto deberia ir despues del que tiene foto',
        )

    def test_orden_por_precio_no_se_altera(self):
        """Si el cliente elige otro orden, se respeta su criterio."""
        self.sin_foto.precio_base = Decimal('5000')   # mas barato
        self.sin_foto.save()
        resp = self.client.get(reverse('ecommerce:catalogo') + '?sort=low')
        body = resp.content.decode()
        self.assertLess(body.index('AAA Sin Foto'), body.index('ZZZ Con Foto'))
