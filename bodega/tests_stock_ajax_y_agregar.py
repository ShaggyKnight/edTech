"""Tests de los filtros AJAX en /bodega/ y de la pantalla
'Cargar stock inicial' para productos sin stock.
"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.test import TestCase
from django.urls import reverse

from bodega.models import (
    MovimientoStock, StockTienda, Tienda,
)
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


class StockFiltersAJAXTests(TestCase):
    """StockView devuelve solo la tabla cuando es HTMX."""

    @classmethod
    def setUpTestData(cls):
        cls.tienda = Tienda.objects.create(
            nombre_organizacion='Tienda Centro', activa=True,
        )
        cls.fam = Familia.objects.create(nombre='Perfumes')
        p = Producto.objects.create(
            familia=cls.fam, nombre='Yara EDP',
            precio_base=Decimal('25000'), tiene_variantes=False,
        )
        StockTienda.objects.create(
            tienda=cls.tienda, producto=p, cantidad=3,
        )
        cls.bodeguero = _crear_user(
            'bod', 'bodeguero', perms=['view_stocktienda'],
        )

    def setUp(self):
        self.client.force_login(self.bodeguero)
        self.url = reverse('bodega:stock')

    def test_pagina_completa_sin_htmx(self):
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 200)
        # Header de la pagina + filtros + tabla.
        self.assertContains(r, '<h1>Stock por tienda</h1>')
        self.assertContains(r, 'id="stock-tabla"')
        self.assertContains(r, 'Yara EDP')

    def test_htmx_devuelve_solo_la_tabla(self):
        r = self.client.get(self.url, HTTP_HX_REQUEST='true')
        self.assertEqual(r.status_code, 200)
        # Solo el partial — sin <h1>, sin filtros.
        self.assertContains(r, 'id="stock-tabla"')
        self.assertNotContains(r, '<h1>Stock por tienda</h1>')

    def test_htmx_filtro_por_q(self):
        # Otro producto que no matchea.
        otro = Producto.objects.create(
            familia=self.fam, nombre='Light Blue',
            precio_base=Decimal('30000'), tiene_variantes=False,
        )
        StockTienda.objects.create(
            tienda=self.tienda, producto=otro, cantidad=2,
        )
        r = self.client.get(self.url, {'q': 'Yara'}, HTTP_HX_REQUEST='true')
        self.assertContains(r, 'Yara EDP')
        self.assertNotContains(r, 'Light Blue')


class StockAgregarTests(TestCase):
    """Pantalla 'Cargar stock inicial' para productos nuevos."""

    @classmethod
    def setUpTestData(cls):
        cls.tienda = Tienda.objects.create(
            nombre_organizacion='Tienda Centro', activa=True,
        )
        cls.fam = Familia.objects.create(nombre='Perfumes')

        # Producto sin variantes, sin stock todavia.
        cls.simple = Producto.objects.create(
            familia=cls.fam, nombre='Yara EDP',
            precio_base=Decimal('25000'), tiene_variantes=False,
        )

        # Producto con variantes, sin stock.
        cls.con_var = Producto.objects.create(
            familia=cls.fam, nombre='Tous Gold',
            precio_base=Decimal('30000'), tiene_variantes=True,
        )
        atr_vol = Atributo.objects.create(nombre='Volumen')
        val_50 = ValorAtributo.objects.create(
            atributo=atr_vol, valor='50 ml', orden=3,
        )
        cls.var_50 = ProductoVariante.objects.create(
            producto=cls.con_var, sku='PERF-TOUS-50-EDP', activa=True,
        )
        cls.var_50.valores.add(val_50)

        cls.admin = _crear_user('adm', 'admin')
        cls.bodeguero = _crear_user('bod', 'bodeguero', perms=['view_stocktienda'])
        cls.cajero = _crear_user('caj', 'cajero')
        cls.url = reverse('bodega:stock_agregar')

    # ── GET ────────────────────────────────────────────────────────

    def test_get_admin_ve_form(self):
        self.client.force_login(self.admin)
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 200)
        # La variante aparece en el select agrupado por familia.
        self.assertContains(r, 'Tous Gold')
        self.assertContains(r, 'PERF-TOUS-50-EDP')
        # El producto sin variantes tambien.
        self.assertContains(r, 'Yara EDP')

    def test_get_bodeguero_ve_form(self):
        self.client.force_login(self.bodeguero)
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 200)

    def test_get_cajero_redirige(self):
        """`@reponer_required` no aplica via decorator pero la view
        valida `_puede_reponer` y redirige al cajero."""
        self.client.force_login(self.cajero)
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 302)

    def test_get_anonimo_redirige_login(self):
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 302)
        self.assertIn('/login', r.url)

    # ── POST ───────────────────────────────────────────────────────

    def test_post_crea_stock_de_variante(self):
        self.client.force_login(self.admin)
        r = self.client.post(self.url, {
            'tipo': 'v',
            'item_id': self.var_50.pk,
            'tienda_id': self.tienda.pk,
            'cantidad': 5,
        })
        self.assertEqual(r.status_code, 302)
        # Stock creado con la cantidad sumada.
        fila = StockTienda.objects.get(tienda=self.tienda, variante=self.var_50)
        self.assertEqual(fila.cantidad, 5)
        # Movimiento auditoria creado.
        mov = MovimientoStock.objects.get(variante=self.var_50)
        self.assertEqual(mov.tipo, MovimientoStock.ENTRADA)
        self.assertEqual(mov.cantidad, 5)

    def test_post_crea_stock_de_producto_directo(self):
        self.client.force_login(self.admin)
        r = self.client.post(self.url, {
            'tipo': 'p',
            'item_id': self.simple.pk,
            'tienda_id': self.tienda.pk,
            'cantidad': 10,
        })
        self.assertEqual(r.status_code, 302)
        fila = StockTienda.objects.get(tienda=self.tienda, producto=self.simple)
        self.assertEqual(fila.cantidad, 10)

    def test_post_segunda_vez_suma_a_la_primera(self):
        """Si el producto ya tiene stock, suma (no reemplaza)."""
        self.client.force_login(self.admin)
        self.client.post(self.url, {
            'tipo': 'v', 'item_id': self.var_50.pk,
            'tienda_id': self.tienda.pk, 'cantidad': 5,
        })
        self.client.post(self.url, {
            'tipo': 'v', 'item_id': self.var_50.pk,
            'tienda_id': self.tienda.pk, 'cantidad': 3,
        })
        fila = StockTienda.objects.get(tienda=self.tienda, variante=self.var_50)
        self.assertEqual(fila.cantidad, 8)

    def test_post_cantidad_invalida_no_crea_stock(self):
        self.client.force_login(self.admin)
        r = self.client.post(self.url, {
            'tipo': 'v', 'item_id': self.var_50.pk,
            'tienda_id': self.tienda.pk, 'cantidad': 0,
        })
        self.assertEqual(r.status_code, 302)
        self.assertFalse(StockTienda.objects.filter(variante=self.var_50).exists())

    def test_post_cantidad_negativa_no_crea_stock(self):
        self.client.force_login(self.admin)
        r = self.client.post(self.url, {
            'tipo': 'v', 'item_id': self.var_50.pk,
            'tienda_id': self.tienda.pk, 'cantidad': -5,
        })
        self.assertEqual(r.status_code, 302)
        self.assertFalse(StockTienda.objects.filter(variante=self.var_50).exists())

    def test_post_tipo_invalido_no_crea_stock(self):
        self.client.force_login(self.admin)
        r = self.client.post(self.url, {
            'tipo': 'x', 'item_id': self.var_50.pk,
            'tienda_id': self.tienda.pk, 'cantidad': 5,
        })
        self.assertEqual(r.status_code, 302)
        self.assertFalse(StockTienda.objects.exists())

    def test_post_variante_inactiva_rechaza(self):
        self.var_50.activa = False
        self.var_50.save()
        self.client.force_login(self.admin)
        r = self.client.post(self.url, {
            'tipo': 'v', 'item_id': self.var_50.pk,
            'tienda_id': self.tienda.pk, 'cantidad': 5,
        })
        self.assertEqual(r.status_code, 302)
        self.assertFalse(StockTienda.objects.filter(variante=self.var_50).exists())

    def test_post_cajero_no_puede(self):
        self.client.force_login(self.cajero)
        r = self.client.post(self.url, {
            'tipo': 'v', 'item_id': self.var_50.pk,
            'tienda_id': self.tienda.pk, 'cantidad': 5,
        })
        self.assertEqual(r.status_code, 302)
        self.assertFalse(StockTienda.objects.filter(variante=self.var_50).exists())

    def test_post_redirige_a_misma_pagina_para_cargar_mas(self):
        """UX: tras guardar, vuelve al form vacio para cargar el
        siguiente producto sin tener que navegar."""
        self.client.force_login(self.admin)
        r = self.client.post(self.url, {
            'tipo': 'p', 'item_id': self.simple.pk,
            'tienda_id': self.tienda.pk, 'cantidad': 5,
        })
        self.assertRedirects(r, self.url)
