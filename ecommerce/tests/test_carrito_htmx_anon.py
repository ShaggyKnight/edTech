"""Tests E2E del carrito como usuario anonimo, incluyendo el flow
HTMX de +/-/quitar/vaciar (Bloque: carrito HTMX).

Bug reportado: 'cuando alguien entra a la tienda y no esta logueado,
al agregar al carrito no pasa nada'. Estos tests confirman que el
backend SI responde correctamente — el bug (si existe) es solo de
UX/frontend, no de logica.
"""
from decimal import Decimal

from django.test import TestCase, override_settings
from django.urls import reverse

from bodega.models import StockTienda, Tienda
from catalogo.models import (
    Atributo, Familia, Producto, ProductoVariante, ValorAtributo,
)


@override_settings(ECOMMERCE_PAYMENT_GATEWAY='mock')
class CarritoAnonimoTests(TestCase):
    """E2E: cliente anonimo agrega → ve → modifica → vacia."""

    @classmethod
    def setUpTestData(cls):
        cls.tienda = Tienda.objects.create(
            nombre_organizacion='Online', activa=True,
        )
        cls.fam = Familia.objects.create(nombre='Perfumes')

        # Producto sin variantes (mas simple).
        cls.simple = Producto.objects.create(
            familia=cls.fam, nombre='Yara EDP',
            precio_base=Decimal('25000'), tiene_variantes=False,
        )
        StockTienda.objects.create(
            tienda=cls.tienda, producto=cls.simple, cantidad=5,
        )

        # Producto con variantes.
        cls.con_var = Producto.objects.create(
            familia=cls.fam, nombre='Tous Gold',
            precio_base=Decimal('30000'), tiene_variantes=True,
        )
        atr_vol = Atributo.objects.create(nombre='Volumen')
        val_50 = ValorAtributo.objects.create(
            atributo=atr_vol, valor='50 ml', orden=3,
        )
        cls.var_50 = ProductoVariante.objects.create(
            producto=cls.con_var, sku='TG-50', activa=True,
        )
        cls.var_50.valores.add(val_50)
        StockTienda.objects.create(
            tienda=cls.tienda, variante=cls.var_50, cantidad=3,
        )

    def setUp(self):
        self.so = self.settings(ECOMMERCE_TIENDA_ID=self.tienda.pk)
        self.so.enable()
        # Cliente sin login — esto es crucial: el carrito debe
        # funcionar igual para anonimos que para registrados.
        self.assertFalse('_auth_user_id' in self.client.session)

    def tearDown(self):
        self.so.disable()

    # ── Agregar ────────────────────────────────────────────────────

    def test_anon_agrega_producto_simple(self):
        r = self.client.post(reverse('ecommerce:agregar'), {
            'tipo': 'p',
            'item_id': self.simple.pk,
            'cantidad': 1,
        })
        # No-HTMX: redirect al carrito.
        self.assertEqual(r.status_code, 302)
        # Carrito persistido en session.
        cart = self.client.session.get('ecommerce_cart', {})
        self.assertEqual(cart, {f'p:{self.simple.pk}': 1})

    def test_anon_agrega_variante(self):
        r = self.client.post(reverse('ecommerce:agregar'), {
            'tipo': 'v',
            'item_id': self.var_50.pk,
            'cantidad': 2,
        })
        self.assertEqual(r.status_code, 302)
        cart = self.client.session.get('ecommerce_cart', {})
        self.assertEqual(cart, {f'v:{self.var_50.pk}': 2})

    def test_anon_agrega_htmx_devuelve_oob_partial(self):
        """HTMX flow: response es el partial con OOB para actualizar
        el badge del carrito en el header."""
        r = self.client.post(
            reverse('ecommerce:agregar'),
            {'tipo': 'p', 'item_id': self.simple.pk, 'cantidad': 1},
            HTTP_HX_REQUEST='true',
        )
        self.assertEqual(r.status_code, 200)
        # OOB del shop-cart-icon con count 1.
        self.assertContains(r, 'id="shop-cart-icon"')
        self.assertContains(r, 'hx-swap-oob="true"')
        self.assertContains(r, 'cart-dot">1<')
        # Toast con el nombre del producto.
        self.assertContains(r, 'Yara EDP')

    def test_anon_agrega_dos_veces_suma(self):
        """Si el cliente agrega 2 veces el mismo producto, suma cantidades."""
        url = reverse('ecommerce:agregar')
        self.client.post(url, {
            'tipo': 'p', 'item_id': self.simple.pk, 'cantidad': 1,
        })
        self.client.post(url, {
            'tipo': 'p', 'item_id': self.simple.pk, 'cantidad': 2,
        })
        cart = self.client.session.get('ecommerce_cart', {})
        self.assertEqual(cart[f'p:{self.simple.pk}'], 3)

    # ── Ver carrito ────────────────────────────────────────────────

    def test_anon_ve_carrito_con_items(self):
        self.client.post(reverse('ecommerce:agregar'), {
            'tipo': 'p', 'item_id': self.simple.pk, 'cantidad': 2,
        })
        r = self.client.get(reverse('ecommerce:carrito'))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Yara EDP')
        self.assertContains(r, '2 producto')  # "2 productos"
        # Forms de +/- y quitar deben tener HTMX attrs.
        self.assertContains(r, 'hx-post')
        self.assertContains(r, 'hx-target="#cart-content"')

    def test_anon_ve_carrito_vacio(self):
        r = self.client.get(reverse('ecommerce:carrito'))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Tu carrito está vacío')

    # ── Actualizar via HTMX ────────────────────────────────────────

    def test_anon_actualiza_cantidad_via_htmx(self):
        """+/- via HTMX devuelve solo el partial del carrito."""
        self.client.post(reverse('ecommerce:agregar'), {
            'tipo': 'p', 'item_id': self.simple.pk, 'cantidad': 1,
        })
        r = self.client.post(
            reverse('ecommerce:actualizar'),
            {'key': f'p:{self.simple.pk}', 'cantidad': 3},
            HTTP_HX_REQUEST='true',
        )
        self.assertEqual(r.status_code, 200)
        # Es el partial — tiene cart-content sin <h1> de pagina.
        self.assertContains(r, 'id="cart-content"')
        self.assertNotContains(r, '<title>')
        # Carrito actualizado a 3.
        cart = self.client.session.get('ecommerce_cart', {})
        self.assertEqual(cart[f'p:{self.simple.pk}'], 3)

    def test_anon_actualiza_a_cero_quita_el_item(self):
        """Setear cantidad a 0 quita el item del carrito."""
        self.client.post(reverse('ecommerce:agregar'), {
            'tipo': 'p', 'item_id': self.simple.pk, 'cantidad': 2,
        })
        self.client.post(
            reverse('ecommerce:actualizar'),
            {'key': f'p:{self.simple.pk}', 'cantidad': 0},
            HTTP_HX_REQUEST='true',
        )
        cart = self.client.session.get('ecommerce_cart', {})
        self.assertNotIn(f'p:{self.simple.pk}', cart)

    # ── Quitar via HTMX ────────────────────────────────────────────

    def test_anon_quita_via_htmx(self):
        self.client.post(reverse('ecommerce:agregar'), {
            'tipo': 'p', 'item_id': self.simple.pk, 'cantidad': 1,
        })
        r = self.client.post(
            reverse('ecommerce:quitar', args=[f'p:{self.simple.pk}']),
            HTTP_HX_REQUEST='true',
        )
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'id="cart-content"')
        cart = self.client.session.get('ecommerce_cart', {})
        self.assertEqual(cart, {})

    # ── Vaciar via HTMX ────────────────────────────────────────────

    def test_anon_vacia_via_htmx(self):
        self.client.post(reverse('ecommerce:agregar'), {
            'tipo': 'p', 'item_id': self.simple.pk, 'cantidad': 1,
        })
        self.client.post(reverse('ecommerce:agregar'), {
            'tipo': 'v', 'item_id': self.var_50.pk, 'cantidad': 1,
        })
        r = self.client.post(
            reverse('ecommerce:vaciar'),
            HTTP_HX_REQUEST='true',
        )
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Tu carrito está vacío')
        cart = self.client.session.get('ecommerce_cart', {})
        self.assertEqual(cart, {})

    # ── Persistencia entre requests ────────────────────────────────

    def test_carrito_persiste_entre_requests_de_anon(self):
        """El carrito debe mantenerse por toda la sesion del anon."""
        url = reverse('ecommerce:agregar')
        self.client.post(url, {
            'tipo': 'p', 'item_id': self.simple.pk, 'cantidad': 1,
        })
        # Otra request distinta (GET catalogo) — el cart no se pierde.
        self.client.get(reverse('ecommerce:catalogo'))
        cart = self.client.session.get('ecommerce_cart', {})
        self.assertEqual(cart[f'p:{self.simple.pk}'], 1)

    def test_pdp_tiene_form_de_agregar_con_htmx(self):
        """Sanity: el PDP debe renderizar el form con hx-post."""
        r = self.client.get(reverse('ecommerce:producto', args=[self.con_var.pk]))
        self.assertEqual(r.status_code, 200)
        # Form con HTMX.
        self.assertContains(r, 'hx-post="/tienda/agregar/"')
        # CSRF token presente (Django lo requiere incluso para anon).
        self.assertContains(r, 'csrfmiddlewaretoken')
        # Indicator para loading state.
        self.assertContains(r, 'hx-indicator')

    def test_pdp_boton_add_no_usa_disabled_html(self):
        """El boton NO debe usar el atributo `disabled` HTML (que bloquea
        clicks) NI `aria-disabled` (puede causar problemas en algunos
        browsers/HTMX). Usa clase `.needs-selection` para look visual;
        la validacion vive en el JS submit handler basado en hidden.value.

        Si JS falla, el form submite, el server valida vacio item_id y
        responde con error — el cliente nunca ve 'no pasa nada'."""
        r = self.client.get(reverse('ecommerce:producto', args=[self.con_var.pk]))
        self.assertContains(r, 'id="pdp-add-btn"')
        self.assertContains(r, 'needs-selection')
        # Sanity: NO debe tener `disabled` ni `aria-disabled` en la
        # apertura del boton (que bloquearian el click).
        body = r.content.decode('utf-8')
        # Buscar el <button id="pdp-add-btn" ...> y verificar sus attrs.
        import re
        m = re.search(r'<button[^>]*id="pdp-add-btn"[^>]*>', body)
        self.assertIsNotNone(m, 'pdp-add-btn no encontrado')
        tag_open = m.group(0)
        self.assertNotIn(' disabled', tag_open,
                         f'pdp-add-btn no debe tener `disabled`: {tag_open}')
        self.assertNotIn('aria-disabled', tag_open,
                         f'pdp-add-btn no debe tener `aria-disabled`: {tag_open}')
