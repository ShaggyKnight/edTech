"""Bloque 10: tests del toggle inline de `activo` desde la lista
de productos del backoffice. Mismo patron que set_precio: admin
puede, bodeguero/cajero no."""
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


class ToggleActivoTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.fam = Familia.objects.create(nombre='Perfumes')
        cls.producto_activo = Producto.objects.create(
            familia=cls.fam, nombre='Activo X',
            precio_base=Decimal('20000'), tiene_variantes=False,
            activo=True,
        )
        cls.producto_inactivo = Producto.objects.create(
            familia=cls.fam, nombre='Inactivo Y',
            precio_base=Decimal('15000'), tiene_variantes=False,
            activo=False,
        )

        cls.admin = _crear_user('adm', 'admin')
        cls.bodeguero = _crear_user('bod', 'bodeguero', perms=['view_stocktienda'])
        cls.cajero = _crear_user('caj', 'cajero')

    def _url(self, producto):
        return reverse('bodega:producto_toggle_activo', args=[producto.pk])

    def test_admin_puede_desactivar_producto_activo(self):
        self.client.force_login(self.admin)
        resp = self.client.post(self._url(self.producto_activo))
        self.assertEqual(resp.status_code, 302)
        self.producto_activo.refresh_from_db()
        self.assertFalse(self.producto_activo.activo)

    def test_admin_puede_activar_producto_inactivo(self):
        self.client.force_login(self.admin)
        resp = self.client.post(self._url(self.producto_inactivo))
        self.assertEqual(resp.status_code, 302)
        self.producto_inactivo.refresh_from_db()
        self.assertTrue(self.producto_inactivo.activo)

    def test_bodeguero_no_puede_togglear(self):
        """El bodeguero gestiona stock, no discontinua productos."""
        self.client.force_login(self.bodeguero)
        resp = self.client.post(self._url(self.producto_activo))
        # Redirige con error, el estado NO cambia.
        self.assertEqual(resp.status_code, 302)
        self.producto_activo.refresh_from_db()
        self.assertTrue(self.producto_activo.activo)

    def test_cajero_no_puede_togglear(self):
        self.client.force_login(self.cajero)
        resp = self.client.post(self._url(self.producto_activo))
        self.assertEqual(resp.status_code, 302)
        self.producto_activo.refresh_from_db()
        self.assertTrue(self.producto_activo.activo)

    def test_htmx_devuelve_la_celda_con_nuevo_estado(self):
        """HTMX devuelve el partial con el badge actualizado."""
        self.client.force_login(self.admin)
        resp = self.client.post(
            self._url(self.producto_activo),
            HTTP_HX_REQUEST='true',
        )
        self.assertEqual(resp.status_code, 200)
        # El producto quedo desactivado, el partial muestra "Inactivo".
        self.assertContains(resp, 'Inactivo')
        self.assertNotContains(resp, '>Activo</')

    def test_get_no_permitido(self):
        """Solo POST: GET devuelve 405."""
        self.client.force_login(self.admin)
        resp = self.client.get(self._url(self.producto_activo))
        self.assertEqual(resp.status_code, 405)

    def test_anonimo_redirige_a_login(self):
        resp = self.client.post(self._url(self.producto_activo))
        # @login_required redirige.
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/login', resp.url)

    def test_lista_productos_marca_puede_editar_activo_para_admin(self):
        """El context flag se pasa correctamente para que el template
        renderice el badge como boton clickable."""
        self.client.force_login(self.admin)
        resp = self.client.get(reverse('bodega:lista_productos'))
        self.assertEqual(resp.status_code, 200)
        # Boton del partial con hx-post al endpoint.
        self.assertContains(resp, 'producto_toggle_activo' if False else 'toggle-activo')

    def test_lista_productos_no_marca_puede_editar_activo_para_bodeguero(self):
        """El bodeguero NO ve el boton (badge plano)."""
        self.client.force_login(self.bodeguero)
        resp = self.client.get(reverse('bodega:lista_productos'))
        self.assertEqual(resp.status_code, 200)
        # Sin acceso al endpoint en el HTML.
        self.assertNotContains(resp, 'toggle-activo')
