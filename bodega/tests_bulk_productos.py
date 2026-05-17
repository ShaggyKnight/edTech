"""Bloque 11: tests del endpoint bulk-action para productos.

Permite activar/desactivar varios productos a la vez desde la lista.
Mismo modelo de permisos que el toggle individual: solo admin/superuser.
"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.test import TestCase
from django.urls import reverse

from catalogo.models import Familia, Producto

User = get_user_model()


def _crear_user(username, grupo=None, perms=()):
    u = User.objects.create_user(username, password='x')
    if grupo:
        g, _ = Group.objects.get_or_create(name=grupo)
        u.groups.add(g)
    for codename in perms:
        u.user_permissions.add(Permission.objects.get(codename=codename))
    return u


class BulkActionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.fam = Familia.objects.create(nombre='Perfumes')
        cls.p1 = Producto.objects.create(
            familia=cls.fam, nombre='Activo A',
            precio_base=Decimal('1000'), activo=True,
        )
        cls.p2 = Producto.objects.create(
            familia=cls.fam, nombre='Activo B',
            precio_base=Decimal('2000'), activo=True,
        )
        cls.p3 = Producto.objects.create(
            familia=cls.fam, nombre='Inactivo C',
            precio_base=Decimal('3000'), activo=False,
        )

        cls.admin = _crear_user('adm', 'admin')
        cls.bodeguero = _crear_user('bod', 'bodeguero', perms=['view_stocktienda'])
        cls.cajero = _crear_user('caj', 'cajero')
        cls.url = reverse('bodega:productos_bulk_action')

    def test_admin_desactiva_varios_a_la_vez(self):
        self.client.force_login(self.admin)
        resp = self.client.post(self.url, {
            'accion': 'desactivar',
            'ids': [self.p1.pk, self.p2.pk],
        })
        self.assertEqual(resp.status_code, 302)
        self.p1.refresh_from_db()
        self.p2.refresh_from_db()
        self.p3.refresh_from_db()
        self.assertFalse(self.p1.activo)
        self.assertFalse(self.p2.activo)
        self.assertFalse(self.p3.activo)  # ya estaba inactivo, sigue asi

    def test_admin_activa_varios_a_la_vez(self):
        self.client.force_login(self.admin)
        resp = self.client.post(self.url, {
            'accion': 'activar',
            'ids': [self.p3.pk],
        })
        self.assertEqual(resp.status_code, 302)
        self.p3.refresh_from_db()
        self.assertTrue(self.p3.activo)

    def test_bodeguero_no_puede_bulk(self):
        self.client.force_login(self.bodeguero)
        resp = self.client.post(self.url, {
            'accion': 'desactivar',
            'ids': [self.p1.pk],
        })
        self.assertEqual(resp.status_code, 302)
        self.p1.refresh_from_db()
        self.assertTrue(self.p1.activo)  # NO cambio

    def test_cajero_no_puede_bulk(self):
        self.client.force_login(self.cajero)
        resp = self.client.post(self.url, {
            'accion': 'desactivar',
            'ids': [self.p1.pk],
        })
        self.assertEqual(resp.status_code, 302)
        self.p1.refresh_from_db()
        self.assertTrue(self.p1.activo)

    def test_accion_invalida_no_cambia_nada(self):
        self.client.force_login(self.admin)
        resp = self.client.post(self.url, {
            'accion': 'borrar',  # No permitida en esta vista
            'ids': [self.p1.pk],
        })
        self.assertEqual(resp.status_code, 302)
        self.p1.refresh_from_db()
        self.assertTrue(self.p1.activo)

    def test_sin_ids_no_cambia_nada(self):
        self.client.force_login(self.admin)
        resp = self.client.post(self.url, {'accion': 'desactivar'})
        self.assertEqual(resp.status_code, 302)
        self.p1.refresh_from_db()
        self.assertTrue(self.p1.activo)

    def test_htmx_devuelve_tabla_actualizada(self):
        """HTMX: el endpoint re-renderiza la tabla con los filtros vigentes."""
        self.client.force_login(self.admin)
        resp = self.client.post(
            self.url,
            {'accion': 'desactivar', 'ids': [self.p1.pk]},
            HTTP_HX_REQUEST='true',
        )
        self.assertEqual(resp.status_code, 200)
        # Devuelve la tabla con los 3 productos visibles (sin filtro).
        self.assertContains(resp, 'productos-tabla')
        self.assertContains(resp, 'Activo A')
        self.assertContains(resp, 'Activo B')
        self.assertContains(resp, 'Inactivo C')

    def test_htmx_respeta_filtro_de_estado(self):
        """Si el filtro es 'activos', tras desactivar P1 no debe aparecer."""
        self.client.force_login(self.admin)
        resp = self.client.post(
            self.url,
            {
                'accion': 'desactivar',
                'ids': [self.p1.pk],
                'estado': 'activos',
            },
            HTTP_HX_REQUEST='true',
        )
        self.assertEqual(resp.status_code, 200)
        # P1 ahora inactivo + filtro activos = no aparece
        self.assertNotContains(resp, 'Activo A')
        # P2 sigue activo
        self.assertContains(resp, 'Activo B')

    def test_anonimo_redirige_a_login(self):
        resp = self.client.post(self.url, {
            'accion': 'desactivar', 'ids': [self.p1.pk],
        })
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/login', resp.url)

    def test_get_no_permitido(self):
        self.client.force_login(self.admin)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 405)
