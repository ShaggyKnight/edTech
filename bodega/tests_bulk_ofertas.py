"""Bloque 13: tests del bulk-action de ofertas (mismo patron que productos)."""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from catalogo.models import Familia, Oferta, Producto

User = get_user_model()


def _crear_user(username, grupo=None, perms=()):
    u = User.objects.create_user(username, password='x')
    if grupo:
        g, _ = Group.objects.get_or_create(name=grupo)
        u.groups.add(g)
    for codename in perms:
        u.user_permissions.add(Permission.objects.get(codename=codename))
    return u


class BulkOfertasTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.fam = Familia.objects.create(nombre='Perfumes')
        cls.prod = Producto.objects.create(
            familia=cls.fam, nombre='Yara', precio_base=Decimal('20000'),
        )
        ahora = timezone.now()

        cls.o1 = Oferta.objects.create(
            nombre='Oferta A', producto=cls.prod, tipo='porcentaje',
            valor=Decimal('10'), canal='online',
            fecha_inicio=ahora, fecha_fin=ahora + timedelta(days=10),
            activa=True,
        )
        cls.o2 = Oferta.objects.create(
            nombre='Oferta B', producto=cls.prod, tipo='porcentaje',
            valor=Decimal('15'), canal='online',
            fecha_inicio=ahora, fecha_fin=ahora + timedelta(days=10),
            activa=True,
        )
        cls.o3 = Oferta.objects.create(
            nombre='Oferta C (pausada)', producto=cls.prod, tipo='porcentaje',
            valor=Decimal('20'), canal='online',
            fecha_inicio=ahora, fecha_fin=ahora + timedelta(days=10),
            activa=False,
        )

        cls.admin = _crear_user('adm', 'admin')
        cls.bodeguero = _crear_user('bod', 'bodeguero', perms=['view_stocktienda'])
        cls.cajero = _crear_user('caj', 'cajero')
        cls.url = reverse('bodega:ofertas_bulk_action')

    def test_admin_pausa_varias_a_la_vez(self):
        self.client.force_login(self.admin)
        resp = self.client.post(self.url, {
            'accion': 'pausar',
            'ids': [self.o1.pk, self.o2.pk],
        })
        self.assertEqual(resp.status_code, 302)
        self.o1.refresh_from_db()
        self.o2.refresh_from_db()
        self.assertFalse(self.o1.activa)
        self.assertFalse(self.o2.activa)

    def test_admin_reactiva(self):
        self.client.force_login(self.admin)
        resp = self.client.post(self.url, {
            'accion': 'reactivar',
            'ids': [self.o3.pk],
        })
        self.assertEqual(resp.status_code, 302)
        self.o3.refresh_from_db()
        self.assertTrue(self.o3.activa)

    def test_bodeguero_no_puede(self):
        self.client.force_login(self.bodeguero)
        resp = self.client.post(self.url, {
            'accion': 'pausar', 'ids': [self.o1.pk],
        })
        # `@ofertas_required` redirige a login.
        self.assertEqual(resp.status_code, 302)
        self.o1.refresh_from_db()
        self.assertTrue(self.o1.activa)  # NO cambio

    def test_cajero_no_puede(self):
        self.client.force_login(self.cajero)
        resp = self.client.post(self.url, {
            'accion': 'pausar', 'ids': [self.o1.pk],
        })
        self.assertEqual(resp.status_code, 302)
        self.o1.refresh_from_db()
        self.assertTrue(self.o1.activa)

    def test_accion_invalida(self):
        self.client.force_login(self.admin)
        resp = self.client.post(self.url, {
            'accion': 'borrar', 'ids': [self.o1.pk],
        })
        self.assertEqual(resp.status_code, 302)
        self.o1.refresh_from_db()
        self.assertTrue(self.o1.activa)

    def test_sin_ids(self):
        self.client.force_login(self.admin)
        resp = self.client.post(self.url, {'accion': 'pausar'})
        self.assertEqual(resp.status_code, 302)
        self.o1.refresh_from_db()
        self.assertTrue(self.o1.activa)

    def test_htmx_devuelve_tabla(self):
        self.client.force_login(self.admin)
        resp = self.client.post(
            self.url,
            {'accion': 'pausar', 'ids': [self.o1.pk]},
            HTTP_HX_REQUEST='true',
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'ofertas-tabla')

    def test_get_no_permitido(self):
        self.client.force_login(self.admin)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 405)

    def test_lista_marca_puede_bulk_para_admin(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse('bodega:lista_ofertas'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'bulk-ofertas-form')

    def test_lista_no_marca_puede_bulk_para_bodeguero(self):
        self.client.force_login(self.bodeguero)
        resp = self.client.get(reverse('bodega:lista_ofertas'))
        # bodeguero NO ve la lista de ofertas (ofertas_required) — redirige.
        self.assertEqual(resp.status_code, 302)
