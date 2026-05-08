"""Tests del endpoint set_stock (edicion inline desde la pantalla
de stock — clic en el numero, Enter para guardar)."""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.test import TestCase
from django.urls import reverse

from bodega.models import MovimientoStock, StockTienda, Tienda
from catalogo.models import Familia, Producto

User = get_user_model()


class SetStockTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tienda = Tienda.objects.create(nombre_organizacion='LV', activa=True)
        cls.fam = Familia.objects.create(nombre='Uniformes')
        cls.producto = Producto.objects.create(
            familia=cls.fam, nombre='Polera DP',
            precio_base=Decimal('12000'), tiene_variantes=False,
        )
        cls.fila = StockTienda.objects.create(
            tienda=cls.tienda, producto=cls.producto, cantidad=10,
        )

        cls.bodeguero = User.objects.create_user('bod', password='x')
        g_bod, _ = Group.objects.get_or_create(name='bodeguero')
        cls.bodeguero.groups.add(g_bod)
        cls.bodeguero.user_permissions.add(
            Permission.objects.get(codename='view_stocktienda'),
        )

        cls.cajero = User.objects.create_user('caj', password='x')
        g_caj, _ = Group.objects.get_or_create(name='cajero')
        cls.cajero.groups.add(g_caj)

    def _set(self, cantidad, htmx=False):
        kwargs = {}
        if htmx:
            kwargs['HTTP_HX_REQUEST'] = 'true'
        return self.client.post(
            reverse('bodega:set_stock', args=[self.fila.pk]),
            {'cantidad': cantidad},
            **kwargs,
        )

    def test_bodeguero_puede_subir_stock(self):
        self.client.force_login(self.bodeguero)
        resp = self._set(15)
        self.assertEqual(resp.status_code, 302)
        self.fila.refresh_from_db()
        self.assertEqual(self.fila.cantidad, 15)
        # Audit: delta +5 → MovimientoStock.ENTRADA con cantidad=5.
        mov = MovimientoStock.objects.filter(
            producto=self.producto, tipo=MovimientoStock.ENTRADA,
        ).get()
        self.assertEqual(mov.cantidad, 5)
        self.assertIn('Ajuste manual', mov.referencia)

    def test_bodeguero_puede_bajar_stock(self):
        self.client.force_login(self.bodeguero)
        resp = self._set(3)
        self.assertEqual(resp.status_code, 302)
        self.fila.refresh_from_db()
        self.assertEqual(self.fila.cantidad, 3)
        # Audit: delta -7 → MovimientoStock.SALIDA con cantidad=7.
        mov = MovimientoStock.objects.filter(
            producto=self.producto, tipo=MovimientoStock.SALIDA,
        ).get()
        self.assertEqual(mov.cantidad, 7)

    def test_setear_misma_cantidad_no_genera_movimiento(self):
        self.client.force_login(self.bodeguero)
        self._set(10)  # ya estaba en 10
        self.assertFalse(MovimientoStock.objects.exists())

    def test_cajero_no_puede_editar(self):
        self.client.force_login(self.cajero)
        resp = self._set(5)
        self.assertEqual(resp.status_code, 302)
        self.fila.refresh_from_db()
        self.assertEqual(self.fila.cantidad, 10)  # sin cambios

    def test_cantidad_negativa_rechaza(self):
        self.client.force_login(self.bodeguero)
        resp = self._set(-5)
        self.fila.refresh_from_db()
        self.assertEqual(self.fila.cantidad, 10)

    def test_cantidad_no_numerica_rechaza(self):
        self.client.force_login(self.bodeguero)
        resp = self.client.post(
            reverse('bodega:set_stock', args=[self.fila.pk]),
            {'cantidad': 'abc'},
        )
        self.fila.refresh_from_db()
        self.assertEqual(self.fila.cantidad, 10)

    def test_cantidad_fuera_de_rango_rechaza(self):
        self.client.force_login(self.bodeguero)
        self._set(999999)
        self.fila.refresh_from_db()
        self.assertEqual(self.fila.cantidad, 10)

    def test_htmx_devuelve_solo_la_fila(self):
        self.client.force_login(self.bodeguero)
        resp = self._set(20, htmx=True)
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode().lower()
        self.assertNotIn('<html', body)
        self.assertIn(f'row-stock-{self.fila.pk}', body)
        # Y la cantidad nueva ya esta renderizada.
        self.assertIn('20', body)

    def test_anonimo_redirige_login(self):
        resp = self._set(5)
        self.assertEqual(resp.status_code, 302)
        self.fila.refresh_from_db()
        self.assertEqual(self.fila.cantidad, 10)
