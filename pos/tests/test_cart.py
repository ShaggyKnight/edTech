"""Tests del carrito en sesión (pos.cart.Cart)."""

from datetime import timedelta
from decimal import Decimal

from django.test import RequestFactory, TestCase
from django.utils import timezone

from catalogo.models import Atributo, Familia, Oferta, Producto, ProductoVariante, ValorAtributo
from pos.cart import Cart


def _fake_session():
    """Session-like dict con atributo `modified` (lo que Cart usa)."""
    class _Session(dict):
        modified = False
    return _Session()


class CartBasicoTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.familia = Familia.objects.create(nombre='Perfumes')
        cls.producto_simple = Producto.objects.create(
            familia=cls.familia,
            nombre='Perfume 30ml',
            precio_base=Decimal('15000'),
            tiene_variantes=False,
        )
        cls.producto_var = Producto.objects.create(
            familia=cls.familia,
            nombre='Polera Colegio',
            precio_base=Decimal('8000'),
            tiene_variantes=True,
        )
        talla = Atributo.objects.create(nombre='Talla')
        cls.talla_m = ValorAtributo.objects.create(atributo=talla, valor='M')
        cls.variante = ProductoVariante.objects.create(
            producto=cls.producto_var,
            sku='POL-M',
            precio_override=Decimal('9000'),
        )
        cls.variante.valores.add(cls.talla_m)

    def test_add_y_lineas_producto_simple(self):
        cart = Cart(_fake_session())
        cart.add_producto(self.producto_simple.pk, cantidad=2)

        lineas = list(cart.lineas())
        self.assertEqual(len(lineas), 1)
        linea = lineas[0]
        self.assertEqual(linea['tipo'], 'p')
        self.assertEqual(linea['cantidad'], 2)
        self.assertEqual(linea['precio_unitario'], Decimal('15000'))
        self.assertEqual(linea['descuento_unitario'], Decimal('0'))
        self.assertEqual(linea['subtotal'], Decimal('30000'))

    def test_add_y_lineas_variante_usa_precio_override(self):
        cart = Cart(_fake_session())
        cart.add_variante(self.variante.pk, cantidad=1)

        linea = next(iter(cart.lineas()))
        self.assertEqual(linea['tipo'], 'v')
        self.assertEqual(linea['precio_unitario'], Decimal('9000'))
        self.assertEqual(linea['subtotal'], Decimal('9000'))

    def test_set_cantidad_cero_elimina_linea(self):
        cart = Cart(_fake_session())
        cart.add_producto(self.producto_simple.pk, cantidad=3)
        cart.set_cantidad(f'p:{self.producto_simple.pk}', 0)
        self.assertTrue(cart.is_empty())

    def test_totales_sin_ofertas(self):
        cart = Cart(_fake_session())
        cart.add_producto(self.producto_simple.pk, cantidad=2)  # 2 x 15000 = 30000
        cart.add_variante(self.variante.pk, cantidad=1)          # 1 x 9000  =  9000
        bruto, descuento, neto = cart.totales()
        self.assertEqual(bruto, Decimal('39000'))
        self.assertEqual(descuento, Decimal('0'))
        self.assertEqual(neto, Decimal('39000'))


class CartOfertasTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.familia = Familia.objects.create(nombre='Perfumes')
        cls.producto = Producto.objects.create(
            familia=cls.familia,
            nombre='Perfume 30ml',
            precio_base=Decimal('10000'),
            tiene_variantes=False,
        )
        ahora = timezone.now()
        cls.oferta = Oferta.objects.create(
            nombre='10% off presencial',
            producto=cls.producto,
            tipo=Oferta.TIPO_PORCENTAJE,
            valor=Decimal('10'),
            canal=Oferta.CANAL_PRESENCIAL,
            fecha_inicio=ahora - timedelta(days=1),
            fecha_fin=ahora + timedelta(days=1),
            activa=True,
        )

    def test_oferta_porcentaje_presencial_descuenta(self):
        cart = Cart(_fake_session())
        cart.add_producto(self.producto.pk, cantidad=1)

        linea = next(iter(cart.lineas(canal='presencial')))
        self.assertEqual(linea['descuento_unitario'], Decimal('1000'))
        self.assertEqual(linea['subtotal'], Decimal('9000'))

    def test_oferta_presencial_no_aplica_a_canal_online(self):
        cart = Cart(_fake_session())
        cart.add_producto(self.producto.pk, cantidad=1)

        linea = next(iter(cart.lineas(canal='online')))
        self.assertEqual(linea['descuento_unitario'], Decimal('0'))
        self.assertEqual(linea['subtotal'], Decimal('10000'))
