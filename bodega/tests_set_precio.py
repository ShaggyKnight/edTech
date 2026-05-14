"""Tests del endpoint set_precio (edicion inline desde la lista de
productos del backoffice — clic en el precio, Enter para guardar)."""
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


class SetPrecioTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.fam = Familia.objects.create(nombre='Perfumes')
        cls.producto = Producto.objects.create(
            familia=cls.fam, nombre='Perfume X',
            precio_base=Decimal('20000'), tiene_variantes=False,
        )

        cls.admin = _crear_user('adm', 'admin')
        cls.bodeguero = _crear_user('bod', 'bodeguero', perms=['view_stocktienda'])
        cls.cajero = _crear_user('caj', 'cajero')

    def test_admin_puede_cambiar_precio(self):
        self.client.force_login(self.admin)
        resp = self.client.post(
            reverse('bodega:set_precio', args=[self.producto.pk]),
            {'precio_base': '25000'},
        )
        self.assertEqual(resp.status_code, 302)
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.precio_base, Decimal('25000'))

    def test_bodeguero_no_puede_cambiar_precio(self):
        """El bodeguero gestiona stock, no decide precios."""
        self.client.force_login(self.bodeguero)
        resp = self.client.post(
            reverse('bodega:set_precio', args=[self.producto.pk]),
            {'precio_base': '25000'},
        )
        # Redirige con mensaje de error, el precio NO cambia.
        self.assertEqual(resp.status_code, 302)
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.precio_base, Decimal('20000'))

    def test_cajero_no_puede_cambiar_precio(self):
        self.client.force_login(self.cajero)
        resp = self.client.post(
            reverse('bodega:set_precio', args=[self.producto.pk]),
            {'precio_base': '25000'},
        )
        # Sin permiso de view_stocktienda, redirige al login del backoffice.
        # Si por alguna razon llega al view, igualmente debe fallar.
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.precio_base, Decimal('20000'))

    def test_htmx_devuelve_celda_actualizada(self):
        self.client.force_login(self.admin)
        resp = self.client.post(
            reverse('bodega:set_precio', args=[self.producto.pk]),
            {'precio_base': '25000'},
            HTTP_HX_REQUEST='true',
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        # Devuelve solo el <td>, no la pagina entera.
        self.assertNotIn('<html', body.lower())
        # Contiene el id de la celda y el nuevo precio.
        self.assertIn(f'precio-celda-{self.producto.pk}', body)
        self.assertIn('25.000', body)  # formato locale

    def test_precio_negativo_rechaza(self):
        self.client.force_login(self.admin)
        self.client.post(
            reverse('bodega:set_precio', args=[self.producto.pk]),
            {'precio_base': '-100'},
        )
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.precio_base, Decimal('20000'))

    def test_precio_no_numerico_rechaza(self):
        self.client.force_login(self.admin)
        self.client.post(
            reverse('bodega:set_precio', args=[self.producto.pk]),
            {'precio_base': 'abc'},
        )
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.precio_base, Decimal('20000'))

    def test_precio_acepta_coma_decimal(self):
        """Algunos teclados chilenos usan coma para decimales."""
        self.client.force_login(self.admin)
        self.client.post(
            reverse('bodega:set_precio', args=[self.producto.pk]),
            {'precio_base': '12345,50'},
        )
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.precio_base, Decimal('12345.50'))

    def test_precio_fuera_de_rango_rechaza(self):
        self.client.force_login(self.admin)
        self.client.post(
            reverse('bodega:set_precio', args=[self.producto.pk]),
            {'precio_base': '999999999'},
        )
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.precio_base, Decimal('20000'))

    def test_get_no_aceptado(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse('bodega:set_precio', args=[self.producto.pk]))
        self.assertEqual(resp.status_code, 405)
