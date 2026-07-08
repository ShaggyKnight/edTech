"""El rol despachador ve SOLO la pantalla de despacho.

La duena pidio un despachador "puro": nada de Stock, Ventas, Catalogo ni
Reportes en el sidebar — solo Despacho. El acceso a /despacho/ es por rol.
"""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse

from accounts.roles import DESPACHADOR

User = get_user_model()


class RolDespachadorPuroTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user('dispatch', password='x')
        self.user.groups.add(Group.objects.get(name=DESPACHADOR))
        self.client.force_login(self.user)

    def _sidebar(self):
        # El POS no lo puede abrir; usamos la propia pantalla de despacho,
        # que renderiza base.html con el sidebar completo.
        resp = self.client.get(reverse('despacho:cola'))
        self.assertEqual(resp.status_code, 200)
        return resp.content.decode('utf-8', 'replace')

    def test_dashboard_router_lo_manda_a_despacho(self):
        resp = self.client.get(reverse('accounts:dashboard'))
        self.assertRedirects(resp, reverse('despacho:cola'),
                             fetch_redirect_response=False)

    def test_ve_despacho(self):
        html = self._sidebar()
        self.assertIn('Despacho', html)

    def test_no_ve_stock_ni_ventas_ni_catalogo_ni_reportes(self):
        html = self._sidebar()
        # Secciones/links que NO debe ver un despachador puro.
        self.assertNotIn('>Stock<', html)
        self.assertNotIn('>Ventas<', html)
        self.assertNotIn('>Productos<', html)
        self.assertNotIn('bo-side-section">Catálogo', html)
        self.assertNotIn('bo-side-section">Reportes', html)
        self.assertNotIn('bo-side-section">Administración', html)

    def test_no_puede_entrar_a_stock(self):
        resp = self.client.get(reverse('bodega:stock'))
        # Sin view_stocktienda: PermissionRequiredMixin -> 302 al login o 403.
        self.assertNotEqual(resp.status_code, 200)

    def test_grupo_no_tiene_perms_de_stock_ni_ventas(self):
        codenames = set(
            self.user.groups.get(name=DESPACHADOR)
            .permissions.values_list('codename', flat=True)
        )
        self.assertNotIn('view_stocktienda', codenames)
        self.assertNotIn('view_reciboventa', codenames)
