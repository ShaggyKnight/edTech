"""Bloque 14: tests del bulk-action de materiales."""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.test import TestCase
from django.urls import reverse

from bodega.models import Material, Proveedor

User = get_user_model()


def _crear_user(username, grupo=None, perms=()):
    u = User.objects.create_user(username, password='x')
    if grupo:
        g, _ = Group.objects.get_or_create(name=grupo)
        u.groups.add(g)
    for codename in perms:
        u.user_permissions.add(Permission.objects.get(codename=codename))
    return u


class BulkMaterialesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.prov = Proveedor.objects.create(nombre_proveedor='Tela y Co')
        cls.m1 = Material.objects.create(
            nombre='Polar gris', proveedor=cls.prov,
            costo_unitario_referencia=Decimal('80000'), activo=True,
        )
        cls.m2 = Material.objects.create(
            nombre='Polar rojo', proveedor=cls.prov,
            costo_unitario_referencia=Decimal('80000'), activo=True,
        )
        cls.m3 = Material.objects.create(
            nombre='Polar viejo', proveedor=cls.prov,
            costo_unitario_referencia=Decimal('50000'), activo=False,
        )

        cls.admin = _crear_user('adm', 'admin')
        cls.bodeguero = _crear_user('bod', 'bodeguero', perms=['view_stocktienda'])
        cls.cajero = _crear_user('caj', 'cajero')
        cls.url = reverse('bodega:materiales_bulk_action')

    def test_admin_desactiva_varios(self):
        self.client.force_login(self.admin)
        resp = self.client.post(self.url, {
            'accion': 'desactivar',
            'ids': [self.m1.pk, self.m2.pk],
        })
        self.assertEqual(resp.status_code, 302)
        self.m1.refresh_from_db()
        self.m2.refresh_from_db()
        self.assertFalse(self.m1.activo)
        self.assertFalse(self.m2.activo)

    def test_bodeguero_puede_bulk(self):
        """A diferencia de productos/ofertas, el bodeguero SÍ puede gestionar materiales."""
        self.client.force_login(self.bodeguero)
        resp = self.client.post(self.url, {
            'accion': 'activar',
            'ids': [self.m3.pk],
        })
        self.assertEqual(resp.status_code, 302)
        self.m3.refresh_from_db()
        self.assertTrue(self.m3.activo)

    def test_cajero_no_puede(self):
        self.client.force_login(self.cajero)
        resp = self.client.post(self.url, {
            'accion': 'desactivar', 'ids': [self.m1.pk],
        })
        # @reponer_required redirige a login.
        self.assertEqual(resp.status_code, 302)
        self.m1.refresh_from_db()
        self.assertTrue(self.m1.activo)

    def test_accion_invalida(self):
        self.client.force_login(self.admin)
        resp = self.client.post(self.url, {
            'accion': 'borrar', 'ids': [self.m1.pk],
        })
        self.assertEqual(resp.status_code, 302)
        self.m1.refresh_from_db()
        self.assertTrue(self.m1.activo)

    def test_sin_ids(self):
        self.client.force_login(self.admin)
        resp = self.client.post(self.url, {'accion': 'desactivar'})
        self.assertEqual(resp.status_code, 302)
        self.m1.refresh_from_db()
        self.assertTrue(self.m1.activo)

    def test_htmx_devuelve_tabla(self):
        self.client.force_login(self.admin)
        resp = self.client.post(
            self.url,
            {'accion': 'desactivar', 'ids': [self.m1.pk]},
            HTTP_HX_REQUEST='true',
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'materiales-tabla')

    def test_get_no_permitido(self):
        self.client.force_login(self.admin)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 405)

    def test_lista_marca_puede_bulk(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse('bodega:lista_materiales'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'bulk-materiales-form')
