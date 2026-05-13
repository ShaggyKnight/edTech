"""Tests del endpoint `agregar` con HTMX: agregar al carrito sin
recargar y devolver OOB swaps para el badge del carrito + toasts."""
from decimal import Decimal

from django.test import TestCase, override_settings
from django.urls import reverse

from bodega.models import StockTienda, Tienda
from catalogo.models import (
    Atributo, Familia, Producto, ProductoVariante, ValorAtributo,
)


@override_settings(ECOMMERCE_PAYMENT_GATEWAY='mock')
class AgregarHtmxTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tienda = Tienda.objects.create(nombre_organizacion='Online', activa=True)
        cls.fam = Familia.objects.create(nombre='Perfumes')
        cls.producto = Producto.objects.create(
            familia=cls.fam, nombre='Perfume Test',
            precio_base=Decimal('20000'), tiene_variantes=False,
        )
        StockTienda.objects.create(tienda=cls.tienda, producto=cls.producto, cantidad=5)

        cls.con_variantes = Producto.objects.create(
            familia=cls.fam, nombre='Buzo Test',
            precio_base=Decimal('30000'), tiene_variantes=True,
        )
        cls.atr = Atributo.objects.create(nombre='Talla')
        cls.val_m = ValorAtributo.objects.create(atributo=cls.atr, valor='M', orden=2)
        cls.var_m = ProductoVariante.objects.create(producto=cls.con_variantes, sku='BZ-M')
        cls.var_m.valores.add(cls.val_m)
        StockTienda.objects.create(tienda=cls.tienda, variante=cls.var_m, cantidad=3)

    def setUp(self):
        self.settings_override = self.settings(ECOMMERCE_TIENDA_ID=self.tienda.pk)
        self.settings_override.enable()

    def tearDown(self):
        self.settings_override.disable()

    def _post(self, data, htmx=False):
        kw = {}
        if htmx:
            kw['HTTP_HX_REQUEST'] = 'true'
        return self.client.post(reverse('ecommerce:agregar'), data, **kw)

    def test_post_tradicional_redirige_al_carrito(self):
        """Sin HTMX, mantiene el comportamiento anterior: redirect."""
        resp = self._post({'tipo': 'p', 'item_id': self.producto.pk, 'cantidad': 1})
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/tienda/carrito/', resp.url)

    def test_htmx_no_redirige_devuelve_fragment(self):
        resp = self._post(
            {'tipo': 'p', 'item_id': self.producto.pk, 'cantidad': 1},
            htmx=True,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn('text/html', resp['Content-Type'])
        # No es la pagina completa.
        body = resp.content.decode()
        self.assertNotIn('<html', body.lower())

    def test_htmx_devuelve_oob_del_badge_del_carrito(self):
        resp = self._post(
            {'tipo': 'p', 'item_id': self.producto.pk, 'cantidad': 1},
            htmx=True,
        )
        body = resp.content.decode()
        # OOB del icono del carrito.
        self.assertIn('id="shop-cart-icon"', body)
        self.assertIn('hx-swap-oob="true"', body)
        # cart-dot con el conteo nuevo.
        self.assertIn('class="cart-dot"', body)
        self.assertIn('>1<', body)  # 1 item

    def test_htmx_devuelve_oob_de_toast_de_exito(self):
        resp = self._post(
            {'tipo': 'p', 'item_id': self.producto.pk, 'cantidad': 1},
            htmx=True,
        )
        body = resp.content.decode()
        self.assertIn('id="toast-container"', body)
        self.assertIn('hx-swap-oob="beforeend"', body)
        # Mensaje de exito con el nombre del producto.
        self.assertIn('toast-success', body)
        self.assertIn('Perfume Test', body)

    def test_htmx_variante_muestra_sku_en_toast(self):
        resp = self._post(
            {'tipo': 'v', 'item_id': self.var_m.pk, 'cantidad': 1},
            htmx=True,
        )
        body = resp.content.decode()
        self.assertIn('Buzo Test', body)
        self.assertIn('BZ-M', body)

    def test_htmx_item_inexistente_devuelve_toast_de_error(self):
        resp = self._post(
            {'tipo': 'p', 'item_id': 999999, 'cantidad': 1},
            htmx=True,
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn('toast-error', body)
        self.assertIn('no disponible', body)

    def test_htmx_dos_veces_suma_cantidades(self):
        self._post({'tipo': 'p', 'item_id': self.producto.pk, 'cantidad': 1}, htmx=True)
        resp = self._post(
            {'tipo': 'p', 'item_id': self.producto.pk, 'cantidad': 1},
            htmx=True,
        )
        body = resp.content.decode()
        # Badge muestra 2 items.
        self.assertIn('>2<', body)

    def test_htmx_form_invalido_devuelve_toast_error_sin_modificar_carrito(self):
        resp = self._post({'tipo': 'x'}, htmx=True)
        body = resp.content.decode()
        self.assertIn('toast-error', body)
