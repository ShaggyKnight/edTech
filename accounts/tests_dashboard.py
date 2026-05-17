"""Tests del router /cuenta/dashboard/.

BUG-011: el dashboard genérico debe rutear segun rol:
- admin / superuser → /reportes/
- cajero            → /pos/
- bodeguero         → /bodega/stock/
- cliente sin rol   → /tienda/cuenta/pedidos/ (antes era 403)
"""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse

User = get_user_model()


class DashboardRoutingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        # Los grupos los crea la migracion 0001_crear_roles. Los buscamos
        # en vez de crearlos para no romper el contrato del seed.
        cls.grupo_admin = Group.objects.get(name='admin')
        cls.grupo_cajero = Group.objects.get(name='cajero')
        cls.grupo_bodeguero = Group.objects.get(name='bodeguero')

    def _crear_user(self, username, grupo=None, superuser=False):
        u = User.objects.create_user(username, password='x')
        if superuser:
            u.is_superuser = True
            u.is_staff = True
            u.save()
        if grupo:
            u.groups.add(grupo)
        return u

    def test_anonimo_redirige_a_login(self):
        r = self.client.get(reverse('accounts:dashboard'))
        self.assertEqual(r.status_code, 302)
        self.assertIn('/cuenta/login', r['Location'])

    def test_superuser_va_a_reportes(self):
        self._crear_user('root', superuser=True)
        self.client.login(username='root', password='x')
        r = self.client.get(reverse('accounts:dashboard'))
        self.assertRedirects(r, reverse('reportes:dashboard'),
                             fetch_redirect_response=False)

    def test_admin_grupo_va_a_reportes(self):
        self._crear_user('ana', grupo=self.grupo_admin)
        self.client.login(username='ana', password='x')
        r = self.client.get(reverse('accounts:dashboard'))
        self.assertRedirects(r, reverse('reportes:dashboard'),
                             fetch_redirect_response=False)

    def test_cajero_va_a_pos(self):
        self._crear_user('juan', grupo=self.grupo_cajero)
        self.client.login(username='juan', password='x')
        r = self.client.get(reverse('accounts:dashboard'))
        self.assertRedirects(r, reverse('pos:home'),
                             fetch_redirect_response=False)

    def test_bodeguero_va_a_stock(self):
        self._crear_user('pedro', grupo=self.grupo_bodeguero)
        self.client.login(username='pedro', password='x')
        r = self.client.get(reverse('accounts:dashboard'))
        self.assertRedirects(r, reverse('bodega:stock'),
                             fetch_redirect_response=False)

    def test_cliente_sin_rol_va_a_mis_pedidos(self):
        """BUG-011 regression guard. Cliente normal no debe ver 403."""
        self._crear_user('cliente')
        self.client.login(username='cliente', password='x')
        r = self.client.get(reverse('accounts:dashboard'))
        self.assertEqual(r.status_code, 302,
            'BUG-011: cliente sin rol staff debe redirigir, no 403.')
        self.assertRedirects(r, reverse('ecommerce:mis_pedidos'),
                             fetch_redirect_response=False)
