"""Tests del rol OPERADOR — operación completa simplificada (dueña).

Ve: POS, Ventas, Despacho, Stock, Productos, Ofertas.
NO ve: Materiales, Etiquetas, Reportes, Admin Django, Usuarios.
"""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse

from accounts.roles import OPERADOR

User = get_user_model()


def _crear_operador(username='blanca'):
    user = User.objects.create_user(username, password='x')
    user.groups.add(Group.objects.get(name=OPERADOR))
    return user


class RolOperadorGrupoTests(TestCase):

    def test_migracion_creo_el_grupo_con_permisos(self):
        grupo = Group.objects.get(name=OPERADOR)
        codenames = set(grupo.permissions.values_list('codename', flat=True))
        # Lo que SI puede.
        self.assertIn('change_producto', codenames)
        self.assertIn('change_oferta', codenames)
        self.assertIn('change_stocktienda', codenames)
        self.assertIn('add_reciboventa', codenames)
        self.assertIn('change_reciboventa', codenames)   # marcar despachado
        # Lo que NO puede (simplificacion pedida por la dueña).
        self.assertNotIn('change_material', codenames)
        self.assertNotIn('view_material', codenames)
        self.assertNotIn('view_movimientocaja', codenames)  # reportes


class RolOperadorSidebarTests(TestCase):

    def setUp(self):
        self.user = _crear_operador()
        self.client.force_login(self.user)

    def _html_backoffice(self):
        # El POS home renderiza base.html con el sidebar completo.
        resp = self.client.get(reverse('pos:home'), follow=True)
        self.assertEqual(resp.status_code, 200)
        return resp.content.decode('utf-8', 'replace')

    def test_ve_lo_operativo(self):
        html = self._html_backoffice()
        for esperado in ('Productos', 'Ofertas', 'Stock', 'Despacho', 'POS'):
            self.assertIn(esperado, html)

    def test_no_ve_materiales_ni_etiquetas(self):
        html = self._html_backoffice()
        self.assertNotIn('Materiales', html)
        self.assertNotIn('Etiquetas', html)

    def test_no_ve_reportes_ni_admin(self):
        html = self._html_backoffice()
        self.assertNotIn('Estado de Resultados', html)
        self.assertNotIn('Balance General', html)
        self.assertNotIn('Admin Django', html)
        self.assertNotIn('Usuarios y roles', html)


class RolOperadorAccesoTests(TestCase):

    def setUp(self):
        self.user = _crear_operador()
        self.client.force_login(self.user)

    def test_dashboard_router_lo_manda_al_pos(self):
        resp = self.client.get(reverse('accounts:dashboard'))
        self.assertRedirects(resp, reverse('pos:home'),
                             fetch_redirect_response=False)

    def test_puede_entrar_al_despacho(self):
        resp = self.client.get(reverse('despacho:cola'))
        self.assertEqual(resp.status_code, 200)

    # Acceso REAL a las pantallas (no solo el sidebar): este fue el bug
    # del estreno — el sidebar mostraba Productos pero la vista tenia
    # roles hardcodeados y rebotaba al login pidiendo clave de nuevo.
    def test_puede_entrar_a_productos(self):
        resp = self.client.get(reverse('bodega:lista_productos'))
        self.assertEqual(resp.status_code, 200)

    def test_puede_entrar_a_ofertas(self):
        resp = self.client.get(reverse('bodega:lista_ofertas'))
        self.assertEqual(resp.status_code, 200)

    def test_puede_ver_stock(self):
        resp = self.client.get(reverse('bodega:stock'))
        self.assertEqual(resp.status_code, 200)

    def test_materiales_le_rebota(self):
        resp = self.client.get(reverse('bodega:lista_materiales'))
        self.assertNotEqual(resp.status_code, 200)

    def test_etiquetas_le_rebota(self):
        resp = self.client.get(reverse('bodega:etiquetas_seleccionar'))
        self.assertNotEqual(resp.status_code, 200)

    def test_reportes_le_rebota(self):
        resp = self.client.get(reverse('reportes:dashboard'))
        # Sin permiso de contabilidad: redirect al login o 403, nunca 200.
        self.assertNotEqual(resp.status_code, 200)
