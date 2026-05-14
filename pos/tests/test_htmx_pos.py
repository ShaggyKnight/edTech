"""Tests del flujo HTMX del POS:
- Live search: GET con HX-Request devuelve solo el tbody.
- Agregar/quitar/actualizar/vaciar con HX-Request devuelven OOB del
  carrito + toasts, sin redirect.
- Sin HTMX, el comportamiento tradicional (redirect) se mantiene.
"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.test import TestCase
from django.urls import reverse

from bodega.models import StockTienda, Tienda
from catalogo.models import (
    Atributo, Familia, Producto, ProductoVariante, ValorAtributo,
)
from pos.services import SESSION_TIENDA_KEY

User = get_user_model()


class PosHtmxFlowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tienda = Tienda.objects.create(nombre_organizacion='LV', activa=True)
        cls.fam = Familia.objects.create(nombre='Perfumes')
        cls.fam_uni = Familia.objects.create(nombre='Uniformes')

        cls.perfume = Producto.objects.create(
            familia=cls.fam, nombre='Perfume Yara',
            precio_base=Decimal('20000'), tiene_variantes=False,
        )
        StockTienda.objects.create(tienda=cls.tienda, producto=cls.perfume, cantidad=5)

        cls.perfume_sin_stock = Producto.objects.create(
            familia=cls.fam, nombre='Perfume Agotado',
            precio_base=Decimal('15000'), tiene_variantes=False,
        )
        StockTienda.objects.create(tienda=cls.tienda, producto=cls.perfume_sin_stock, cantidad=0)

        cls.buzo = Producto.objects.create(
            familia=cls.fam_uni, nombre='Buzo SFJ',
            precio_base=Decimal('30000'), tiene_variantes=True,
        )
        cls.atr = Atributo.objects.create(nombre='Talla')
        cls.val_m = ValorAtributo.objects.create(atributo=cls.atr, valor='M', orden=2)
        cls.var_m = ProductoVariante.objects.create(producto=cls.buzo, sku='BZ-M')
        cls.var_m.valores.add(cls.val_m)
        StockTienda.objects.create(tienda=cls.tienda, variante=cls.var_m, cantidad=3)

        cls.cajero = User.objects.create_user('caj', password='x')
        g, _ = Group.objects.get_or_create(name='cajero')
        cls.cajero.groups.add(g)
        cls.cajero.user_permissions.add(
            Permission.objects.get(codename='add_reciboventa'),
        )

    def setUp(self):
        self.client.force_login(self.cajero)
        s = self.client.session
        s[SESSION_TIENDA_KEY] = self.tienda.pk
        s.save()

    # ── Default: solo con stock ───────────────────────────────────────

    def test_default_lista_solo_con_stock(self):
        resp = self.client.get(reverse('pos:home'))
        body = resp.content.decode()
        self.assertIn('Perfume Yara', body)
        self.assertNotIn('Perfume Agotado', body)

    def test_stock_todos_lista_agotados(self):
        resp = self.client.get(reverse('pos:home') + '?stock=todos')
        body = resp.content.decode()
        self.assertIn('Perfume Yara', body)
        self.assertIn('Perfume Agotado', body)

    # ── Live search: HTMX devuelve solo el tbody ──────────────────────

    def test_live_search_htmx_devuelve_solo_tbody(self):
        resp = self.client.get(
            reverse('pos:home') + '?q=Yara',
            HTTP_HX_REQUEST='true',
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        # No es HTML completo.
        self.assertNotIn('<html', body.lower())
        self.assertNotIn('<head', body.lower())
        # Si es el tbody.
        self.assertIn('id="pos-productos-tbody"', body)
        self.assertIn('Perfume Yara', body)
        self.assertNotIn('Buzo SFJ', body)  # filtrado por q=Yara

    def test_live_search_sin_htmx_devuelve_pagina_completa(self):
        resp = self.client.get(reverse('pos:home') + '?q=Yara')
        body = resp.content.decode()
        self.assertIn('<html', body.lower())
        self.assertIn('Perfume Yara', body)

    def test_live_search_filtro_familia(self):
        resp = self.client.get(
            reverse('pos:home') + f'?familia={self.fam_uni.pk}',
            HTTP_HX_REQUEST='true',
        )
        body = resp.content.decode()
        self.assertIn('Buzo SFJ', body)
        self.assertNotIn('Perfume Yara', body)

    # ── Busqueda multi-token (nombre + talla, etc) ────────────────────

    def test_busqueda_multi_token_buzo_talla(self):
        """`buzo 10` debe matchear la talla 10 del Buzo, no la 12."""
        val_12 = ValorAtributo.objects.create(atributo=self.atr, valor='12', orden=3)
        val_10 = ValorAtributo.objects.create(atributo=self.atr, valor='10', orden=4)
        var_10 = ProductoVariante.objects.create(producto=self.buzo, sku='BZ-10')
        var_10.valores.add(val_10)
        StockTienda.objects.create(tienda=self.tienda, variante=var_10, cantidad=2)
        var_12 = ProductoVariante.objects.create(producto=self.buzo, sku='BZ-12')
        var_12.valores.add(val_12)
        StockTienda.objects.create(tienda=self.tienda, variante=var_12, cantidad=2)

        resp = self.client.get(
            reverse('pos:home') + '?q=buzo+10',
            HTTP_HX_REQUEST='true',
        )
        body = resp.content.decode()
        # La variante 10 SI esta.
        self.assertIn('BZ-10', body)
        # La variante 12 NO esta.
        self.assertNotIn('BZ-12', body)
        # La variante M (sin "10" en ningun lado) tampoco.
        self.assertNotIn('BZ-M', body)
        # El perfume Yara (no tiene "buzo") tampoco.
        self.assertNotIn('Perfume Yara', body)

    def test_busqueda_multi_token_orden_independiente(self):
        """`10 buzo` debe dar el mismo resultado que `buzo 10`."""
        val_10 = ValorAtributo.objects.create(atributo=self.atr, valor='10', orden=4)
        var_10 = ProductoVariante.objects.create(producto=self.buzo, sku='BZ-10')
        var_10.valores.add(val_10)
        StockTienda.objects.create(tienda=self.tienda, variante=var_10, cantidad=2)

        resp = self.client.get(
            reverse('pos:home') + '?q=10+buzo',
            HTTP_HX_REQUEST='true',
        )
        self.assertIn('BZ-10', resp.content.decode())

    def test_busqueda_token_unico_funciona(self):
        """Token unico (sin espacios) sigue funcionando como antes."""
        resp = self.client.get(
            reverse('pos:home') + '?q=yara',
            HTTP_HX_REQUEST='true',
        )
        body = resp.content.decode()
        self.assertIn('Perfume Yara', body)
        self.assertNotIn('Buzo SFJ', body)

    def test_busqueda_token_sin_match_devuelve_vacio(self):
        resp = self.client.get(
            reverse('pos:home') + '?q=xyz999',
            HTTP_HX_REQUEST='true',
        )
        body = resp.content.decode()
        self.assertIn('No hay productos', body)

    # ── Agregar al carrito con HTMX ───────────────────────────────────

    def test_agregar_htmx_devuelve_oob_del_carrito(self):
        resp = self.client.post(
            reverse('pos:agregar'),
            {'tipo': 'p', 'item_id': self.perfume.pk, 'cantidad': 1},
            HTTP_HX_REQUEST='true',
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        # Carrito con OOB swap.
        self.assertIn('id="pos-carrito-card"', body)
        self.assertIn('hx-swap-oob="true"', body)
        # 1 item en el carrito.
        self.assertIn('Carrito (1 item)', body)
        # Toast de exito.
        self.assertIn('toast-success', body)
        self.assertIn('Perfume Yara', body)

    def test_agregar_tradicional_sin_htmx_redirige(self):
        """Sin HTMX, mantiene el redirect tradicional como fallback."""
        resp = self.client.post(
            reverse('pos:agregar'),
            {'tipo': 'p', 'item_id': self.perfume.pk, 'cantidad': 1},
        )
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/pos/', resp.url)

    def test_agregar_htmx_dos_veces_suma_en_el_carrito(self):
        self.client.post(
            reverse('pos:agregar'),
            {'tipo': 'p', 'item_id': self.perfume.pk, 'cantidad': 1},
            HTTP_HX_REQUEST='true',
        )
        resp = self.client.post(
            reverse('pos:agregar'),
            {'tipo': 'p', 'item_id': self.perfume.pk, 'cantidad': 1},
            HTTP_HX_REQUEST='true',
        )
        body = resp.content.decode()
        self.assertIn('Carrito (2 item', body)

    def test_agregar_htmx_variante_muestra_sku(self):
        resp = self.client.post(
            reverse('pos:agregar'),
            {'tipo': 'v', 'item_id': self.var_m.pk, 'cantidad': 1},
            HTTP_HX_REQUEST='true',
        )
        body = resp.content.decode()
        self.assertIn('Buzo SFJ', body)
        self.assertIn('BZ-M', body)

    def test_agregar_htmx_item_invalido_devuelve_toast_error(self):
        resp = self.client.post(
            reverse('pos:agregar'),
            {'tipo': 'p', 'item_id': 999999, 'cantidad': 1},
            HTTP_HX_REQUEST='true',
        )
        body = resp.content.decode()
        self.assertIn('toast-error', body)
        # El carrito sigue vacio en el OOB.
        self.assertIn('Carrito vacío', body)

    # ── Quitar / vaciar con HTMX ──────────────────────────────────────

    def test_quitar_htmx_devuelve_oob_del_carrito(self):
        # Primero agrego algo.
        self.client.post(
            reverse('pos:agregar'),
            {'tipo': 'p', 'item_id': self.perfume.pk, 'cantidad': 1},
            HTTP_HX_REQUEST='true',
        )
        resp = self.client.post(
            reverse('pos:quitar', args=[f'p:{self.perfume.pk}']),
            HTTP_HX_REQUEST='true',
        )
        body = resp.content.decode()
        self.assertIn('Carrito vacío', body)

    def test_vaciar_htmx_devuelve_oob_con_toast(self):
        self.client.post(
            reverse('pos:agregar'),
            {'tipo': 'p', 'item_id': self.perfume.pk, 'cantidad': 1},
            HTTP_HX_REQUEST='true',
        )
        resp = self.client.post(
            reverse('pos:vaciar'),
            HTTP_HX_REQUEST='true',
        )
        body = resp.content.decode()
        self.assertIn('Carrito vacío', body)
        self.assertIn('toast-success', body)
