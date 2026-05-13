"""Tests del endpoint POS /pos/escanear/ que agrega items al carrito
a partir de un codigo de barras."""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.test import TestCase
from django.urls import reverse

from bodega.models import StockTienda, Tienda
from catalogo.barcode import generar_codigo_interno
from catalogo.models import Familia, Producto, ProductoVariante
from pos.services import SESSION_TIENDA_KEY

User = get_user_model()


class EscanearTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tienda = Tienda.objects.create(nombre_organizacion='LV', activa=True)
        cls.fam = Familia.objects.create(nombre='Perfumes')

        cls.cajero = User.objects.create_user('caj', password='x')
        g, _ = Group.objects.get_or_create(name='cajero')
        cls.cajero.groups.add(g)
        cls.cajero.user_permissions.add(
            Permission.objects.get(codename='add_reciboventa'),
        )

        # Producto sin variantes con codigo interno.
        cls.perfume = Producto.objects.create(
            familia=cls.fam, nombre='Perfume Yara',
            precio_base=Decimal('19990'), tiene_variantes=False,
        )
        cls.perfume.codigo_barras = generar_codigo_interno('p', cls.perfume.pk)
        cls.perfume.save()
        StockTienda.objects.create(tienda=cls.tienda, producto=cls.perfume, cantidad=10)

        # Producto con variantes — el codigo va en cada variante.
        cls.fam_uni = Familia.objects.create(nombre='Uniformes')
        cls.buzo = Producto.objects.create(
            familia=cls.fam_uni, nombre='Buzo SFJ',
            precio_base=Decimal('30000'), tiene_variantes=True,
        )
        cls.var_m = ProductoVariante.objects.create(producto=cls.buzo, sku='BZ-M')
        cls.var_m.codigo_barras = generar_codigo_interno('v', cls.var_m.pk)
        cls.var_m.save()
        StockTienda.objects.create(tienda=cls.tienda, variante=cls.var_m, cantidad=5)

        # Producto con codigo "externo" (no interno, simulando EAN comercial).
        cls.colonia = Producto.objects.create(
            familia=cls.fam, nombre='Colonia Avella',
            precio_base=Decimal('12990'), tiene_variantes=False,
            codigo_barras='7806950000034',  # codigo externo arbitrario
        )
        StockTienda.objects.create(tienda=cls.tienda, producto=cls.colonia, cantidad=3)

    def setUp(self):
        self.client.force_login(self.cajero)
        # Selecciona la tienda activa en la sesion.
        s = self.client.session
        s[SESSION_TIENDA_KEY] = self.tienda.pk
        s.save()

    def _escanear(self, codigo, htmx=False):
        kw = {}
        if htmx:
            kw['HTTP_HX_REQUEST'] = 'true'
        return self.client.post(reverse('pos:escanear'), {'codigo': codigo}, **kw)

    def test_escanear_codigo_interno_de_producto(self):
        resp = self._escanear(self.perfume.codigo_barras)
        self.assertEqual(resp.status_code, 302)
        # El producto quedó en el carrito.
        from pos.cart import Cart
        cart = Cart(self.client.session)
        keys = [linea['key'] for linea in cart.lineas()]
        self.assertIn(f'p:{self.perfume.pk}', keys)

    def test_escanear_codigo_interno_de_variante(self):
        resp = self._escanear(self.var_m.codigo_barras)
        self.assertEqual(resp.status_code, 302)
        from pos.cart import Cart
        cart = Cart(self.client.session)
        keys = [linea['key'] for linea in cart.lineas()]
        self.assertIn(f'v:{self.var_m.pk}', keys)

    def test_escanear_codigo_externo_de_producto(self):
        """Codigo EAN-13 de fabrica que no es interno — debe matchear
        por la columna codigo_barras directo."""
        resp = self._escanear('7806950000034')
        self.assertEqual(resp.status_code, 302)
        from pos.cart import Cart
        cart = Cart(self.client.session)
        keys = [linea['key'] for linea in cart.lineas()]
        self.assertIn(f'p:{self.colonia.pk}', keys)

    def test_escanear_codigo_inexistente(self):
        resp = self._escanear('9999999999990')
        self.assertEqual(resp.status_code, 302)
        # Nada se agrego.
        from pos.cart import Cart
        cart = Cart(self.client.session)
        self.assertEqual(list(cart.lineas()), [])

    def test_escanear_sin_codigo(self):
        resp = self.client.post(reverse('pos:escanear'), {'codigo': ''})
        self.assertEqual(resp.status_code, 302)

    def test_escanear_dos_veces_suma_cantidades(self):
        """Escanear el mismo codigo dos veces debe sumar al carrito,
        no duplicar lineas."""
        self._escanear(self.perfume.codigo_barras)
        self._escanear(self.perfume.codigo_barras)
        from pos.cart import Cart
        cart = Cart(self.client.session)
        lineas = list(cart.lineas())
        # Una sola linea con cantidad 2.
        self.assertEqual(len(lineas), 1)
        self.assertEqual(lineas[0]['cantidad'], 2)

    def test_escanear_htmx_devuelve_hx_refresh(self):
        """Cuando es request HTMX, no devolvemos HTML — header
        HX-Refresh: true para que el navegador recargue toda la pagina
        y muestre los toasts del messages framework."""
        resp = self._escanear(self.perfume.codigo_barras, htmx=True)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get('HX-Refresh'), 'true')
        self.assertEqual(resp.content, b'')

    def test_codigo_interno_con_pk_que_no_existe_no_crashea(self):
        """Si alguien escanea un codigo que parece interno pero apunta
        a un pk inexistente, debe fallar limpio."""
        codigo_fantasma = generar_codigo_interno('p', 9999999)
        resp = self._escanear(codigo_fantasma)
        self.assertEqual(resp.status_code, 302)
        from pos.cart import Cart
        cart = Cart(self.client.session)
        self.assertEqual(list(cart.lineas()), [])

    def test_escanear_solo_acepta_post(self):
        resp = self.client.get(reverse('pos:escanear'))
        self.assertEqual(resp.status_code, 405)
