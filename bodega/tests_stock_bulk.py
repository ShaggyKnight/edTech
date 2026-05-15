"""Tests de la carga masiva de stock (admin only)."""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.test import TestCase
from django.urls import reverse

from bodega.models import MovimientoStock, StockTienda, Tienda
from catalogo.models import (
    Atributo, Familia, Producto, ProductoVariante, ValorAtributo,
)

User = get_user_model()


def _crear_user(username, grupo=None, perms=()):
    u = User.objects.create_user(username, password='x')
    if grupo:
        g, _ = Group.objects.get_or_create(name=grupo)
        u.groups.add(g)
    for codename in perms:
        u.user_permissions.add(Permission.objects.get(codename=codename))
    return u


class StockBulkAgregarTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tienda = Tienda.objects.create(
            nombre_organizacion='Centro', activa=True,
        )
        cls.fam = Familia.objects.create(nombre='Perfumes')

        # Producto sin variantes, sin stock.
        cls.p_sin_stock = Producto.objects.create(
            familia=cls.fam, nombre='Yara EDP',
            precio_base=Decimal('20000'), tiene_variantes=False,
        )
        # Producto sin variantes con stock.
        cls.p_con_stock = Producto.objects.create(
            familia=cls.fam, nombre='Light Blue',
            precio_base=Decimal('30000'), tiene_variantes=False,
        )
        StockTienda.objects.create(
            tienda=cls.tienda, producto=cls.p_con_stock, cantidad=10,
        )

        # Variante sin stock.
        cls.con_var = Producto.objects.create(
            familia=cls.fam, nombre='Tous Gold',
            precio_base=Decimal('30000'), tiene_variantes=True,
        )
        atr = Atributo.objects.create(nombre='Volumen')
        val_50 = ValorAtributo.objects.create(atributo=atr, valor='50 ml', orden=3)
        cls.var_50 = ProductoVariante.objects.create(
            producto=cls.con_var, sku='TG-50', activa=True,
        )
        cls.var_50.valores.add(val_50)

        # Variante inactiva (no debe aparecer en el form).
        cls.var_inactiva = ProductoVariante.objects.create(
            producto=cls.con_var, sku='TG-INACTIVA', activa=False,
        )

        cls.admin = _crear_user('adm', 'admin')
        cls.bodeguero = _crear_user('bod', 'bodeguero', perms=['view_stocktienda'])
        cls.cajero = _crear_user('caj', 'cajero')
        cls.url = reverse('bodega:stock_bulk_agregar')

    # ── GET / permisos ────────────────────────────────────────────

    def test_get_admin_ve_form(self):
        self.client.force_login(self.admin)
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 200)
        # El form lista los productos.
        self.assertContains(r, 'Yara EDP')
        self.assertContains(r, 'Tous Gold')
        self.assertContains(r, 'Light Blue')
        # Inputs por fila — naming convention qty_v_X o qty_p_X.
        self.assertContains(r, f'qty_p_{self.p_sin_stock.pk}')
        self.assertContains(r, f'qty_v_{self.var_50.pk}')

    def test_get_admin_no_lista_variantes_inactivas(self):
        self.client.force_login(self.admin)
        r = self.client.get(self.url)
        self.assertNotContains(r, f'qty_v_{self.var_inactiva.pk}')

    def test_get_bodeguero_redirige(self):
        """Solo admin — bodeguero no puede acceder."""
        self.client.force_login(self.bodeguero)
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 302)

    def test_get_cajero_redirige(self):
        self.client.force_login(self.cajero)
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 302)

    def test_get_anonimo_redirige_a_login(self):
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 302)
        self.assertIn('/login', r.url)

    # ── Filtro "solo sin stock" ────────────────────────────────────

    def test_filtro_solo_sin_stock_oculta_los_que_tienen(self):
        self.client.force_login(self.admin)
        r = self.client.get(self.url, {'solo_sin_stock': '1'})
        self.assertContains(r, 'Yara EDP')      # sin stock — aparece
        self.assertContains(r, 'Tous Gold')     # variante sin stock
        self.assertNotContains(r, 'Light Blue') # tiene stock — oculto

    # ── POST: carga masiva ────────────────────────────────────────

    def test_admin_carga_varios_productos_a_la_vez(self):
        self.client.force_login(self.admin)
        r = self.client.post(self.url, {
            'tienda_id': self.tienda.pk,
            f'qty_p_{self.p_sin_stock.pk}': '3',
            f'qty_v_{self.var_50.pk}': '5',
            f'qty_p_{self.p_con_stock.pk}': '2',
        })
        self.assertEqual(r.status_code, 302)

        # Stock creado para los que no tenian.
        fila_p = StockTienda.objects.get(tienda=self.tienda, producto=self.p_sin_stock)
        self.assertEqual(fila_p.cantidad, 3)

        fila_v = StockTienda.objects.get(tienda=self.tienda, variante=self.var_50)
        self.assertEqual(fila_v.cantidad, 5)

        # Stock SUMADO al existente.
        fila_existente = StockTienda.objects.get(tienda=self.tienda, producto=self.p_con_stock)
        self.assertEqual(fila_existente.cantidad, 12)  # 10 + 2

        # 3 movimientos auditoria.
        self.assertEqual(MovimientoStock.objects.count(), 3)
        for m in MovimientoStock.objects.all():
            self.assertEqual(m.tipo, MovimientoStock.ENTRADA)
            self.assertEqual(m.usuario, self.admin)

    def test_filas_con_cantidad_0_se_ignoran(self):
        self.client.force_login(self.admin)
        r = self.client.post(self.url, {
            'tienda_id': self.tienda.pk,
            f'qty_p_{self.p_sin_stock.pk}': '0',   # ignorado
            f'qty_v_{self.var_50.pk}': '5',
        })
        self.assertEqual(r.status_code, 302)
        # Solo se creo stock para uno.
        self.assertFalse(StockTienda.objects.filter(
            tienda=self.tienda, producto=self.p_sin_stock,
        ).exists())
        self.assertTrue(StockTienda.objects.filter(
            tienda=self.tienda, variante=self.var_50,
        ).exists())

    def test_filas_con_cantidad_invalida_se_ignoran(self):
        self.client.force_login(self.admin)
        r = self.client.post(self.url, {
            'tienda_id': self.tienda.pk,
            f'qty_p_{self.p_sin_stock.pk}': 'abc',   # no numerico
            f'qty_v_{self.var_50.pk}': '-3',          # negativo
        })
        self.assertEqual(r.status_code, 302)
        # Nada se cargo.
        self.assertEqual(StockTienda.objects.exclude(producto=self.p_con_stock).count(), 0)

    def test_sin_ninguna_cantidad_no_crea_stock(self):
        self.client.force_login(self.admin)
        r = self.client.post(self.url, {'tienda_id': self.tienda.pk})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(MovimientoStock.objects.count(), 0)

    def test_bodeguero_no_puede_bulk(self):
        self.client.force_login(self.bodeguero)
        r = self.client.post(self.url, {
            'tienda_id': self.tienda.pk,
            f'qty_p_{self.p_sin_stock.pk}': '3',
        })
        self.assertEqual(r.status_code, 302)
        # No se creo stock — bodeguero rechazado.
        self.assertFalse(StockTienda.objects.filter(
            tienda=self.tienda, producto=self.p_sin_stock,
        ).exists())

    def test_cajero_no_puede_bulk(self):
        self.client.force_login(self.cajero)
        r = self.client.post(self.url, {
            'tienda_id': self.tienda.pk,
            f'qty_p_{self.p_sin_stock.pk}': '3',
        })
        self.assertEqual(r.status_code, 302)
        self.assertFalse(StockTienda.objects.filter(
            tienda=self.tienda, producto=self.p_sin_stock,
        ).exists())

    def test_variante_inactiva_se_ignora_aun_si_envian_qty(self):
        """Defensa: aun si alguien hace POST forjado con qty_v_<id> de
        una variante inactiva, no se carga stock."""
        self.client.force_login(self.admin)
        r = self.client.post(self.url, {
            'tienda_id': self.tienda.pk,
            f'qty_v_{self.var_inactiva.pk}': '5',
        })
        self.assertEqual(r.status_code, 302)
        self.assertFalse(StockTienda.objects.filter(
            variante=self.var_inactiva,
        ).exists())

    def test_tienda_invalida_rechaza(self):
        self.client.force_login(self.admin)
        r = self.client.post(self.url, {
            'tienda_id': 999999,
            f'qty_p_{self.p_sin_stock.pk}': '5',
        })
        self.assertEqual(r.status_code, 302)
        self.assertFalse(StockTienda.objects.filter(producto=self.p_sin_stock).exists())

    def test_stock_pantalla_muestra_boton_solo_a_admin(self):
        # Admin ve el boton.
        self.client.force_login(self.admin)
        r = self.client.get(reverse('bodega:stock'))
        self.assertContains(r, 'Carga masiva')
        self.assertContains(r, 'stock/bulk')
        # Bodeguero no.
        self.client.force_login(self.bodeguero)
        r = self.client.get(reverse('bodega:stock'))
        self.assertNotContains(r, 'Carga masiva')
        self.assertNotContains(r, 'stock/bulk')
