"""Tests del POS para la mejora de filtros + carga rápida de stock por admin.

Cubre:
- Filtros por familia, búsqueda y `solo con stock` (default ON).
- Carga rápida de stock: solo admin/superuser puede; cajero recibe error.
"""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.test import TestCase
from django.urls import reverse

from bodega.models import MovimientoStock, StockTienda, Tienda
from catalogo.models import Familia, Producto

User = get_user_model()


class PosFiltrosTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tienda = Tienda.objects.create(nombre_organizacion='LV', activa=True)
        cls.fam_unif = Familia.objects.create(nombre='Uniformes')
        cls.fam_perf = Familia.objects.create(nombre='Perfumes')

        cls.buzo = Producto.objects.create(
            familia=cls.fam_unif, nombre='Buzo SFJ',
            precio_base=Decimal('25000'), tiene_variantes=False,
        )
        cls.perfume = Producto.objects.create(
            familia=cls.fam_perf, nombre='Eau de Toilette',
            precio_base=Decimal('18000'), tiene_variantes=False,
        )
        cls.calzon = Producto.objects.create(
            familia=cls.fam_perf, nombre='Calzon agotado',
            precio_base=Decimal('5000'), tiene_variantes=False,
        )
        # Stocks: buzo y perfume con stock; calzon sin stock.
        StockTienda.objects.create(tienda=cls.tienda, producto=cls.buzo, cantidad=10)
        StockTienda.objects.create(tienda=cls.tienda, producto=cls.perfume, cantidad=5)
        StockTienda.objects.create(tienda=cls.tienda, producto=cls.calzon, cantidad=0)

        # Cajero con permiso para usar el POS.
        cls.cajero = User.objects.create_user('vendedor', password='x')
        cls.cajero.user_permissions.add(
            *Permission.objects.filter(codename__in=[
                'add_reciboventa', 'view_reciboventa', 'view_producto',
                'view_productovariante', 'view_familia', 'view_oferta',
                'view_tienda', 'view_stocktienda',
            ])
        )

    def setUp(self):
        self.client.force_login(self.cajero)
        s = self.client.session
        s['tienda_activa_id'] = self.tienda.pk
        s.save()

    def test_default_oculta_agotados(self):
        resp = self.client.get(reverse('pos:home'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Buzo SFJ')
        self.assertContains(resp, 'Eau de Toilette')
        # Calzon agotado NO debe aparecer por default (solo con stock).
        self.assertNotContains(resp, 'Calzon agotado')

    def test_stock_todos_muestra_agotados(self):
        resp = self.client.get(reverse('pos:home') + '?stock=todos')
        self.assertContains(resp, 'Calzon agotado')
        self.assertContains(resp, 'Buzo SFJ')

    def test_filtro_por_familia(self):
        resp = self.client.get(
            reverse('pos:home') + f'?familia={self.fam_unif.pk}'
        )
        self.assertContains(resp, 'Buzo SFJ')
        self.assertNotContains(resp, 'Eau de Toilette')

    def test_busqueda_por_nombre(self):
        resp = self.client.get(reverse('pos:home') + '?q=Buzo')
        self.assertContains(resp, 'Buzo SFJ')
        self.assertNotContains(resp, 'Eau de Toilette')


class SumarStockRemovidoDelPosTests(TestCase):
    """Confirmar que el POS NO tiene mas la opcion de cargar stock.

    El stock se maneja desde /bodega/stock/ por bodegueros y admins —
    el POS solo opera ventas. Removido 2026-05-21.
    """

    @classmethod
    def setUpTestData(cls):
        cls.tienda = Tienda.objects.create(nombre_organizacion='LV', activa=True)
        cls.fam = Familia.objects.create(nombre='Uniformes')
        cls.producto = Producto.objects.create(
            familia=cls.fam, nombre='Buzo',
            precio_base=Decimal('25000'), tiene_variantes=False,
        )
        cls.admin = User.objects.create_superuser('root', 'r@x.cl', 'x')

    def _set_tienda(self):
        s = self.client.session
        s['tienda_activa_id'] = self.tienda.pk
        s.save()

    def test_url_agregar_stock_ya_no_existe(self):
        from django.urls import NoReverseMatch
        with self.assertRaises(NoReverseMatch):
            reverse('pos:agregar_stock')

    def test_boton_sumar_stock_no_aparece_ni_para_admin(self):
        """El boton "+ Stock" se removio del POS. Ni admin lo ve."""
        self.client.force_login(self.admin)
        self._set_tienda()
        StockTienda.objects.create(tienda=self.tienda, producto=self.producto, cantidad=5)
        resp = self.client.get(reverse('pos:home'))
        self.assertNotContains(resp, '/pos/agregar-stock/')
        self.assertNotContains(resp, '+ Stock')
