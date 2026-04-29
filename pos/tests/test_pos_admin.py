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


class AgregarStockTests(TestCase):
    """Carga rápida de stock desde el POS — solo admin/superuser."""

    @classmethod
    def setUpTestData(cls):
        cls.tienda = Tienda.objects.create(nombre_organizacion='LV', activa=True)
        cls.fam = Familia.objects.create(nombre='Uniformes')
        cls.producto = Producto.objects.create(
            familia=cls.fam, nombre='Buzo',
            precio_base=Decimal('25000'), tiene_variantes=False,
        )
        # Cajero con permisos POS.
        cls.cajero = User.objects.create_user('caj', password='x')
        cls.cajero.user_permissions.add(
            *Permission.objects.filter(codename='add_reciboventa')
        )
        # Admin (superuser).
        cls.admin = User.objects.create_superuser('root', 'r@x.cl', 'x')
        # Admin via grupo (no superuser pero en grupo `admin`).
        cls.grupo_admin, _ = Group.objects.get_or_create(name='admin')
        cls.admin_grupo = User.objects.create_user('manager', password='x')
        cls.admin_grupo.groups.add(cls.grupo_admin)
        cls.admin_grupo.user_permissions.add(
            *Permission.objects.filter(codename='add_reciboventa')
        )

    def _set_tienda(self):
        s = self.client.session
        s['tienda_activa_id'] = self.tienda.pk
        s.save()

    def test_cajero_no_puede_cargar_stock(self):
        self.client.force_login(self.cajero)
        self._set_tienda()
        resp = self.client.post(reverse('pos:agregar_stock'), {
            'tipo': 'p', 'item_id': self.producto.pk, 'cantidad': 5,
        })
        # Redirige y no crea stock.
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(StockTienda.objects.filter(producto=self.producto).exists())

    def test_superuser_puede_cargar_stock(self):
        self.client.force_login(self.admin)
        self._set_tienda()
        resp = self.client.post(reverse('pos:agregar_stock'), {
            'tipo': 'p', 'item_id': self.producto.pk, 'cantidad': 12,
        })
        self.assertEqual(resp.status_code, 302)
        st = StockTienda.objects.get(producto=self.producto, tienda=self.tienda)
        self.assertEqual(st.cantidad, 12)
        # Audit log creado.
        self.assertEqual(
            MovimientoStock.objects.filter(
                tipo=MovimientoStock.ENTRADA, producto=self.producto,
            ).count(), 1,
        )

    def test_admin_grupo_tambien_puede(self):
        self.client.force_login(self.admin_grupo)
        self._set_tienda()
        resp = self.client.post(reverse('pos:agregar_stock'), {
            'tipo': 'p', 'item_id': self.producto.pk, 'cantidad': 7,
        })
        self.assertEqual(resp.status_code, 302)
        st = StockTienda.objects.get(producto=self.producto, tienda=self.tienda)
        self.assertEqual(st.cantidad, 7)

    def test_carga_acumula_sobre_stock_existente(self):
        StockTienda.objects.create(
            tienda=self.tienda, producto=self.producto, cantidad=3,
        )
        self.client.force_login(self.admin)
        self._set_tienda()
        self.client.post(reverse('pos:agregar_stock'), {
            'tipo': 'p', 'item_id': self.producto.pk, 'cantidad': 10,
        })
        st = StockTienda.objects.get(producto=self.producto)
        self.assertEqual(st.cantidad, 13)

    def test_cantidad_invalida_no_aplica(self):
        self.client.force_login(self.admin)
        self._set_tienda()
        resp = self.client.post(reverse('pos:agregar_stock'), {
            'tipo': 'p', 'item_id': self.producto.pk, 'cantidad': 0,
        })
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(StockTienda.objects.exists())

    def test_boton_cargar_no_aparece_para_cajero(self):
        """Smoke: en el HTML del POS el form de +Stock no aparece si user no es admin."""
        self.client.force_login(self.cajero)
        self._set_tienda()
        StockTienda.objects.create(tienda=self.tienda, producto=self.producto, cantidad=5)
        resp = self.client.get(reverse('pos:home'))
        # El form action /pos/agregar-stock/ solo se renderea para admin.
        self.assertNotContains(resp, '/pos/agregar-stock/')
        self.assertNotContains(resp, '+ Stock')

    def test_boton_cargar_aparece_para_admin(self):
        self.client.force_login(self.admin)
        self._set_tienda()
        StockTienda.objects.create(tienda=self.tienda, producto=self.producto, cantidad=5)
        resp = self.client.get(reverse('pos:home'))
        self.assertContains(resp, '/pos/agregar-stock/')
        self.assertContains(resp, '+ Stock')
