"""Smoke test end-to-end del POS presencial con el cliente de pruebas de Django."""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.test import TestCase, override_settings
from django.urls import reverse

from bodega.models import StockTienda, Tienda
from catalogo.models import Familia, Producto
from pos.models import ReciboVenta


User = get_user_model()


@override_settings(PAYMENT_GATEWAY='mock')
class PosFlujoCompletoTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.familia = Familia.objects.create(nombre='Perfumes')
        cls.tienda = Tienda.objects.create(nombre_organizacion='Tienda SMK', activa=True)
        cls.producto = Producto.objects.create(
            familia=cls.familia,
            nombre='Perfume 30ml',
            precio_base=Decimal('12000'),
            tiene_variantes=False,
        )
        StockTienda.objects.create(tienda=cls.tienda, producto=cls.producto, cantidad=10)

        cajero_grp, _ = Group.objects.get_or_create(name='cajero')
        perms = Permission.objects.filter(
            content_type__app_label='pos',
            codename__in=['add_reciboventa', 'view_reciboventa'],
        )
        cajero_grp.permissions.add(*perms)

        cls.cajero = User.objects.create_user(username='caja1', password='pass-smk-123')
        cls.cajero.groups.add(cajero_grp)

    def test_flujo_login_agregar_checkout_recibo(self):
        self.assertTrue(self.client.login(username='caja1', password='pass-smk-123'))

        # home se renderiza y autoselecciona la única tienda activa.
        resp = self.client.get(reverse('pos:home'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Perfume 30ml')

        # agregar al carrito.
        resp = self.client.post(reverse('pos:agregar'), {
            'tipo': 'p',
            'item_id': self.producto.pk,
            'cantidad': 2,
        }, follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Carrito (2 items)')

        # checkout.
        resp = self.client.post(reverse('pos:checkout'), {
            'cliente_nombre': 'Juanita',
            'cliente_email': 'j@example.cl',
            'cliente_rut': '',
        }, follow=True)
        self.assertEqual(resp.status_code, 200)

        recibo = ReciboVenta.objects.get()
        self.assertEqual(recibo.estado, ReciboVenta.ESTADO_PAGADO)
        self.assertEqual(recibo.total, Decimal('24000'))
        self.assertEqual(recibo.detalles.count(), 1)
        self.assertEqual(recibo.vendedor, self.cajero)

        # redirige al recibo y se ve.
        self.assertContains(resp, f'Recibo #{recibo.pk}')

        # stock descontado.
        stock = StockTienda.objects.get(tienda=self.tienda, producto=self.producto)
        self.assertEqual(stock.cantidad, 8)

        # listado de ventas: ahora la pk se rendea con prefijo `#` y <strong>.
        resp = self.client.get(reverse('pos:ventas'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, f'#{recibo.pk}')
