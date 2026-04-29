"""Tests del CRUD de productos desde la pantalla de bodega — Fase Ñ."""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.test import TestCase
from django.urls import reverse

from bodega.models import StockTienda, Tienda
from catalogo.models import (
    Atributo, Colegio, Familia, Producto, ProductoVariante, ValorAtributo,
)

User = get_user_model()


class ProductosCrudPermisosTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.fam = Familia.objects.create(nombre='Perfumes')
        cls.cliente = User.objects.create_user('cli', password='x')

        cls.cajero = User.objects.create_user('caj', password='x')
        grupo_cajero, _ = Group.objects.get_or_create(name='cajero')
        cls.cajero.groups.add(grupo_cajero)

        cls.bodeguero = User.objects.create_user('bod', password='x')
        grupo_bod, _ = Group.objects.get_or_create(name='bodeguero')
        cls.bodeguero.groups.add(grupo_bod)

    def test_anonimo_no_accede(self):
        resp = self.client.get(reverse('bodega:lista_productos'))
        self.assertEqual(resp.status_code, 302)

    def test_cajero_no_accede(self):
        self.client.force_login(self.cajero)
        resp = self.client.get(reverse('bodega:lista_productos'))
        self.assertEqual(resp.status_code, 302)

    def test_bodeguero_si_accede(self):
        self.client.force_login(self.bodeguero)
        resp = self.client.get(reverse('bodega:lista_productos'))
        self.assertEqual(resp.status_code, 200)


class ProductoNuevoTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.fam = Familia.objects.create(nombre='Perfumes')
        cls.colegio = Colegio.objects.create(nombre='SFJ', activo=True)
        cls.bodeguero = User.objects.create_user('bod', password='x')
        grupo, _ = Group.objects.get_or_create(name='bodeguero')
        cls.bodeguero.groups.add(grupo)

    def test_crear_producto_simple(self):
        self.client.force_login(self.bodeguero)
        resp = self.client.post(reverse('bodega:producto_nuevo'), {
            'nombre': 'Perfume X',
            'familia': self.fam.pk,
            'colegio': '',
            'descripcion': 'Test',
            'precio_base': '15000',
            'precio_costo': '6000',
            'tiene_variantes': '',
            'activo': 'on',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp['Location'], reverse('bodega:lista_productos'))
        p = Producto.objects.get(nombre='Perfume X')
        self.assertEqual(p.precio_base, Decimal('15000'))
        self.assertFalse(p.tiene_variantes)
        self.assertTrue(p.activo)

    def test_crear_producto_con_variantes_redirige_a_variantes(self):
        self.client.force_login(self.bodeguero)
        resp = self.client.post(reverse('bodega:producto_nuevo'), {
            'nombre': 'Buzo Test',
            'familia': self.fam.pk,
            'colegio': self.colegio.pk,
            'descripcion': '',
            'precio_base': '20000',
            'precio_costo': '8000',
            'tiene_variantes': 'on',
            'activo': 'on',
        })
        self.assertEqual(resp.status_code, 302)
        p = Producto.objects.get(nombre='Buzo Test')
        self.assertTrue(p.tiene_variantes)
        self.assertEqual(p.colegio, self.colegio)
        # Redirige a la lista de variantes para que cargue las primeras.
        self.assertEqual(resp['Location'], reverse('bodega:variantes', args=[p.pk]))

    def test_form_invalido_re_renderea(self):
        self.client.force_login(self.bodeguero)
        resp = self.client.post(reverse('bodega:producto_nuevo'), {
            'nombre': '',  # falta nombre
            'familia': self.fam.pk,
            'precio_base': '10000',
            'precio_costo': '5000',
        })
        self.assertEqual(resp.status_code, 200)
        # No se creó el producto.
        self.assertFalse(Producto.objects.filter(precio_base=Decimal('10000')).exists())


class ProductoEditarTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.fam = Familia.objects.create(nombre='Perfumes')
        cls.bodeguero = User.objects.create_user('bod', password='x')
        grupo, _ = Group.objects.get_or_create(name='bodeguero')
        cls.bodeguero.groups.add(grupo)
        cls.producto = Producto.objects.create(
            familia=cls.fam, nombre='Original', precio_base=Decimal('10000'),
            tiene_variantes=False,
        )

    def test_editar_actualiza_campos(self):
        self.client.force_login(self.bodeguero)
        resp = self.client.post(
            reverse('bodega:producto_editar', args=[self.producto.pk]),
            {
                'nombre': 'Renombrado',
                'familia': self.fam.pk,
                'colegio': '',
                'descripcion': 'Nueva',
                'precio_base': '12000',
                'precio_costo': '5000',
                'tiene_variantes': '',
                'activo': 'on',
            },
        )
        self.assertEqual(resp.status_code, 302)
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.nombre, 'Renombrado')
        self.assertEqual(self.producto.descripcion, 'Nueva')
        self.assertEqual(self.producto.precio_base, Decimal('12000'))


class VarianteCrudTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.fam = Familia.objects.create(nombre='Uniformes')
        cls.bodeguero = User.objects.create_user('bod', password='x')
        grupo, _ = Group.objects.get_or_create(name='bodeguero')
        cls.bodeguero.groups.add(grupo)

        cls.atr_talla = Atributo.objects.create(nombre='Talla')
        cls.val_m = ValorAtributo.objects.create(atributo=cls.atr_talla, valor='M')
        cls.val_l = ValorAtributo.objects.create(atributo=cls.atr_talla, valor='L')

        cls.producto = Producto.objects.create(
            familia=cls.fam, nombre='Buzo', precio_base=Decimal('20000'),
            tiene_variantes=True,
        )
        cls.tienda = Tienda.objects.create(nombre_organizacion='LV', activa=True)

    def test_crear_variante_con_atributo_talla(self):
        self.client.force_login(self.bodeguero)
        resp = self.client.post(
            reverse('bodega:variante_nueva', args=[self.producto.pk]),
            {
                'sku': 'BZ-M',
                f'attr_{self.atr_talla.pk}': self.val_m.pk,
                'precio_override': '',
                'activa': 'on',
            },
        )
        self.assertEqual(resp.status_code, 302)
        v = ProductoVariante.objects.get(sku='BZ-M')
        self.assertEqual(v.producto, self.producto)
        self.assertEqual(list(v.valores.all()), [self.val_m])
        self.assertTrue(v.activa)

    def test_editar_variante_cambia_talla(self):
        v = ProductoVariante.objects.create(producto=self.producto, sku='BZ-M')
        v.valores.add(self.val_m)

        self.client.force_login(self.bodeguero)
        resp = self.client.post(
            reverse('bodega:variante_editar', args=[self.producto.pk, v.pk]),
            {
                'sku': 'BZ-L',
                f'attr_{self.atr_talla.pk}': self.val_l.pk,
                'precio_override': '22000',
                'activa': 'on',
            },
        )
        self.assertEqual(resp.status_code, 302)
        v.refresh_from_db()
        self.assertEqual(v.sku, 'BZ-L')
        self.assertEqual(v.precio_override, Decimal('22000'))
        self.assertEqual(list(v.valores.all()), [self.val_l])

    def test_borrar_sin_stock_elimina(self):
        v = ProductoVariante.objects.create(producto=self.producto, sku='BZ-XS')
        self.client.force_login(self.bodeguero)
        resp = self.client.post(
            reverse('bodega:variante_borrar', args=[self.producto.pk, v.pk]),
        )
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(ProductoVariante.objects.filter(sku='BZ-XS').exists())

    def test_borrar_con_stock_solo_desactiva(self):
        v = ProductoVariante.objects.create(producto=self.producto, sku='BZ-S')
        StockTienda.objects.create(tienda=self.tienda, variante=v, cantidad=3)
        self.client.force_login(self.bodeguero)
        resp = self.client.post(
            reverse('bodega:variante_borrar', args=[self.producto.pk, v.pk]),
        )
        self.assertEqual(resp.status_code, 302)
        v.refresh_from_db()  # sigue existiendo, pero inactiva
        self.assertFalse(v.activa)
