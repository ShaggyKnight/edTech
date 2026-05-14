"""Bloque 6: assertNumQueries — los admin lists no deben hacer N+1.

Si alguien agrega un FK a list_display sin select_related, este test
explota. Mantiene el rendimiento del backoffice barato.
"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from bodega.models import Tienda
from catalogo.models import Colegio, Familia, Producto, ProductoVariante


User = get_user_model()


@override_settings(DEBUG=False)
class AdminListaProductosPerfTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser(
            username='admin@test.cl', email='admin@test.cl', password='x',
        )
        cls.fam_a = Familia.objects.create(nombre='Buzos')
        cls.fam_b = Familia.objects.create(nombre='Perfumes')
        cls.col = Colegio.objects.create(nombre='SFJ')
        # 6 productos: 3 con colegio + 3 sin colegio, mezclando familias.
        for i in range(3):
            Producto.objects.create(
                familia=cls.fam_a, colegio=cls.col,
                nombre=f'Buzo SFJ {i}',
                precio_base=Decimal('20000'),
            )
        for i in range(3):
            Producto.objects.create(
                familia=cls.fam_b,
                nombre=f'Perfume {i}',
                precio_base=Decimal('30000'),
            )

    def test_lista_productos_admin_no_n_plus_1(self):
        """`list_display` con `familia` + `colegio` debe usar select_related.

        Sin el fix, el listado con 6 productos haria 1 + 6 + 6 = 13
        queries. Con select_related quedan ~3-4 (con session/auth).
        """
        self.client.login(username='admin@test.cl', password='x')
        url = reverse('admin:catalogo_producto_changelist')
        # Pre-warm para descartar primera-vez (session, content types).
        self.client.get(url)
        with self.assertNumQueries(__lt=10, __min=1) if False else self.captureQueriesContext() as ctx:
            r = self.client.get(url)
        self.assertEqual(r.status_code, 200)
        # Con 6 productos, sin select_related serian 13+ queries.
        # Con select_related, 6-9 es lo esperado (auth + session +
        # 1 SELECT productos + count + admin overhead).
        n = len(ctx.captured_queries)
        self.assertLess(n, 12, f'Lista de productos hace {n} queries — posible N+1')

    def captureQueriesContext(self):
        # Helper para tener un nombre razonable.
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        return CaptureQueriesContext(connection)


@override_settings(DEBUG=False)
class AdminStockTiendaPerfTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser(
            username='admin@test.cl', email='admin@test.cl', password='x',
        )
        cls.tienda = Tienda.objects.create(nombre_organizacion='T1', activa=True)
        cls.fam = Familia.objects.create(nombre='X')
        prod = Producto.objects.create(familia=cls.fam, nombre='P', precio_base=Decimal('1'),
                                       tiene_variantes=True)
        from bodega.models import StockTienda
        for i in range(5):
            v = ProductoVariante.objects.create(producto=prod, sku=f'P-{i}')
            StockTienda.objects.create(tienda=cls.tienda, variante=v, cantidad=i)

    def test_lista_stock_admin_no_n_plus_1(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        self.client.login(username='admin@test.cl', password='x')
        url = reverse('admin:bodega_stocktienda_changelist')
        self.client.get(url)  # pre-warm
        with CaptureQueriesContext(connection) as ctx:
            r = self.client.get(url)
        self.assertEqual(r.status_code, 200)
        # 3 FKs (tienda + variante + producto) y 5 filas — sin
        # select_related serian 5*3 = 15+ queries extra.
        n = len(ctx.captured_queries)
        self.assertLess(n, 15, f'Lista de stock hace {n} queries — posible N+1')
