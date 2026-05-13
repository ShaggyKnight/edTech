"""Tests del autogenerado de codigo_barras en los forms del backoffice."""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse

from catalogo.barcode import parsear_codigo_interno, validar_ean13
from catalogo.models import Atributo, Familia, Producto, ProductoVariante, ValorAtributo

User = get_user_model()


class CodigoBarrasAutoTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.fam = Familia.objects.create(nombre='Perfumes')
        cls.bodeguero = User.objects.create_user('bod', password='x')
        g, _ = Group.objects.get_or_create(name='bodeguero')
        cls.bodeguero.groups.add(g)

    def setUp(self):
        self.client.force_login(self.bodeguero)

    def test_producto_sin_variantes_codigo_se_genera_al_crear(self):
        resp = self.client.post(reverse('bodega:producto_nuevo'), {
            'nombre': 'Perfume sin código',
            'familia': self.fam.pk,
            'colegio': '',
            'descripcion': '',
            'precio_base': '15000',
            'precio_costo': '8000',
            'tiene_variantes': '',  # off
            'activo': 'on',
            'codigo_barras': '',  # vacio → autogenera
        })
        self.assertEqual(resp.status_code, 302)
        p = Producto.objects.get(nombre='Perfume sin código')
        self.assertTrue(p.codigo_barras)
        self.assertTrue(validar_ean13(p.codigo_barras))
        # Es codigo interno con prefijo 200 y tipo 1 (producto).
        parsed = parsear_codigo_interno(p.codigo_barras)
        self.assertEqual(parsed, ('p', p.pk))

    def test_producto_codigo_manual_se_respeta(self):
        """Si el bodeguero ingresa un EAN-13 (de fabrica), no lo
        sobreescribimos con uno interno."""
        codigo_real = '7806950000034'
        resp = self.client.post(reverse('bodega:producto_nuevo'), {
            'nombre': 'Perfume con EAN real',
            'familia': self.fam.pk,
            'colegio': '',
            'descripcion': '',
            'precio_base': '15000',
            'precio_costo': '8000',
            'tiene_variantes': '',
            'activo': 'on',
            'codigo_barras': codigo_real,
        })
        self.assertEqual(resp.status_code, 302)
        p = Producto.objects.get(nombre='Perfume con EAN real')
        self.assertEqual(p.codigo_barras, codigo_real)

    def test_producto_con_variantes_no_autogenera(self):
        """Si el producto tiene_variantes=True, el codigo de cabecera
        queda vacio — el codigo va a vivir en cada variante."""
        resp = self.client.post(reverse('bodega:producto_nuevo'), {
            'nombre': 'Buzo SFJ',
            'familia': self.fam.pk,
            'colegio': '',
            'descripcion': '',
            'precio_base': '30000',
            'precio_costo': '15000',
            'tiene_variantes': 'on',
            'activo': 'on',
            'codigo_barras': '',
        })
        self.assertEqual(resp.status_code, 302)
        p = Producto.objects.get(nombre='Buzo SFJ')
        self.assertFalse(p.codigo_barras)

    def test_variante_codigo_se_genera_al_crear(self):
        producto = Producto.objects.create(
            familia=self.fam, nombre='Buzo X',
            precio_base=Decimal('30000'), tiene_variantes=True,
        )
        atr = Atributo.objects.create(nombre='Talla')
        ValorAtributo.objects.create(atributo=atr, valor='M', orden=2)

        resp = self.client.post(
            reverse('bodega:variante_nueva', args=[producto.pk]),
            {
                'sku': 'BX-M',
                'precio_override': '',
                'activa': 'on',
                'codigo_barras': '',
                'stock_inicial_cantidad': '0',
            },
        )
        self.assertEqual(resp.status_code, 302)
        v = ProductoVariante.objects.get(sku='BX-M')
        self.assertTrue(v.codigo_barras)
        self.assertTrue(validar_ean13(v.codigo_barras))
        parsed = parsear_codigo_interno(v.codigo_barras)
        self.assertEqual(parsed, ('v', v.pk))

    def test_variante_codigo_manual_se_respeta(self):
        producto = Producto.objects.create(
            familia=self.fam, nombre='Otro Buzo',
            precio_base=Decimal('30000'), tiene_variantes=True,
        )
        codigo_real = '7806950000041'
        resp = self.client.post(
            reverse('bodega:variante_nueva', args=[producto.pk]),
            {
                'sku': 'OB-L',
                'precio_override': '',
                'activa': 'on',
                'codigo_barras': codigo_real,
                'stock_inicial_cantidad': '0',
            },
        )
        self.assertEqual(resp.status_code, 302)
        v = ProductoVariante.objects.get(sku='OB-L')
        self.assertEqual(v.codigo_barras, codigo_real)
