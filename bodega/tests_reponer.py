"""Tests de la pantalla de Stock con reposición — Fase N.

Cubre:
- Filtro por colegio.
- Bodeguero/admin pueden reponer; cajero recibe error.
- Reposición crea MovimientoStock.ENTRADA y bumpea StockTienda atómicamente.
"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.test import TestCase
from django.urls import reverse

from bodega.models import MovimientoStock, StockTienda, Tienda
from catalogo.models import Colegio, Familia, Producto

User = get_user_model()


class StockColegioFiltroTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tienda = Tienda.objects.create(nombre_organizacion='LV', activa=True)
        cls.fam = Familia.objects.create(nombre='Uniformes Escolares')
        cls.sfj = Colegio.objects.create(nombre='SFJ', activo=True)
        cls.dp = Colegio.objects.create(nombre='DP', activo=True)
        cls.buzo_sfj = Producto.objects.create(
            familia=cls.fam, colegio=cls.sfj, nombre='Buzo SFJ',
            precio_base=Decimal('25000'), tiene_variantes=False,
        )
        cls.polera_dp = Producto.objects.create(
            familia=cls.fam, colegio=cls.dp, nombre='Polera DP',
            precio_base=Decimal('12000'), tiene_variantes=False,
        )
        StockTienda.objects.create(tienda=cls.tienda, producto=cls.buzo_sfj, cantidad=10)
        StockTienda.objects.create(tienda=cls.tienda, producto=cls.polera_dp, cantidad=8)

        cls.admin = User.objects.create_superuser('root', 'r@x.cl', 'x')

    def test_filtro_colegio_sfj(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse('bodega:stock') + f'?colegio={self.sfj.pk}')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Buzo SFJ')
        self.assertNotContains(resp, 'Polera DP')

    def test_sin_filtro_muestra_todos_los_colegios(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse('bodega:stock'))
        self.assertContains(resp, 'Buzo SFJ')
        self.assertContains(resp, 'Polera DP')


class ReponerStockTests(TestCase):
    """Reposición de stock — gate por rol bodeguero/admin."""

    @classmethod
    def setUpTestData(cls):
        cls.tienda = Tienda.objects.create(nombre_organizacion='LV', activa=True)
        cls.fam = Familia.objects.create(nombre='Uniformes')
        cls.producto = Producto.objects.create(
            familia=cls.fam, nombre='Buzo SFJ Pantalón',
            precio_base=Decimal('21990'), tiene_variantes=False,
        )

        # Cajero (no puede reponer).
        cls.cajero = User.objects.create_user('caj', password='x')
        grupo_cajero, _ = Group.objects.get_or_create(name='cajero')
        cls.cajero.groups.add(grupo_cajero)
        cls.cajero.user_permissions.add(
            Permission.objects.get(codename='view_stocktienda'),
        )

        # Bodeguero (sí puede).
        cls.bodeguero = User.objects.create_user('bod', password='x')
        grupo_bod, _ = Group.objects.get_or_create(name='bodeguero')
        cls.bodeguero.groups.add(grupo_bod)
        cls.bodeguero.user_permissions.add(
            Permission.objects.get(codename='view_stocktienda'),
        )

        # Admin via grupo.
        cls.admin_grupo = User.objects.create_user('mgr', password='x')
        grupo_admin, _ = Group.objects.get_or_create(name='admin')
        cls.admin_grupo.groups.add(grupo_admin)
        cls.admin_grupo.user_permissions.add(
            Permission.objects.get(codename='view_stocktienda'),
        )

    def _post_reponer(self, cantidad=5):
        return self.client.post(reverse('bodega:reponer'), {
            'tipo': 'p',
            'item_id': self.producto.pk,
            'tienda_id': self.tienda.pk,
            'cantidad': cantidad,
        })

    def test_cajero_no_puede_reponer(self):
        self.client.force_login(self.cajero)
        resp = self._post_reponer(5)
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(StockTienda.objects.filter(producto=self.producto).exists())

    def test_bodeguero_si_puede_reponer(self):
        self.client.force_login(self.bodeguero)
        resp = self._post_reponer(7)
        self.assertEqual(resp.status_code, 302)
        st = StockTienda.objects.get(producto=self.producto, tienda=self.tienda)
        self.assertEqual(st.cantidad, 7)
        # Audit log.
        self.assertEqual(
            MovimientoStock.objects.filter(
                tipo=MovimientoStock.ENTRADA, producto=self.producto,
            ).count(), 1,
        )

    def test_admin_grupo_si_puede(self):
        self.client.force_login(self.admin_grupo)
        resp = self._post_reponer(3)
        self.assertEqual(resp.status_code, 302)
        st = StockTienda.objects.get(producto=self.producto)
        self.assertEqual(st.cantidad, 3)

    def test_form_no_aparece_para_cajero(self):
        StockTienda.objects.create(tienda=self.tienda, producto=self.producto, cantidad=4)
        self.client.force_login(self.cajero)
        resp = self.client.get(reverse('bodega:stock'))
        self.assertNotContains(resp, '/bodega/reponer/')

    def test_form_aparece_para_bodeguero(self):
        StockTienda.objects.create(tienda=self.tienda, producto=self.producto, cantidad=4)
        self.client.force_login(self.bodeguero)
        resp = self.client.get(reverse('bodega:stock'))
        self.assertContains(resp, '/bodega/reponer/')
        self.assertContains(resp, '+ Reponer')

    def test_cantidad_invalida_no_aplica(self):
        self.client.force_login(self.bodeguero)
        resp = self._post_reponer(0)
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(StockTienda.objects.exists())
