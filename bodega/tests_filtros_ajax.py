"""Tests de filtros AJAX en listados del backoffice
(productos, ofertas, materiales).

Verifica que con HX-Request: true la view devuelve solo el partial
de la tabla y filtra correctamente. Sin HTMX, devuelve la pagina
completa (fallback no-JS)."""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from bodega.models import Material, Tienda
from catalogo.models import Familia, Oferta, Producto

User = get_user_model()


def _crear_user(username, grupo=None, perms=()):
    u = User.objects.create_user(username, password='x')
    if grupo:
        g, _ = Group.objects.get_or_create(name=grupo)
        u.groups.add(g)
    for codename in perms:
        u.user_permissions.add(Permission.objects.get(codename=codename))
    return u


class ProductosListaAjaxTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.fam = Familia.objects.create(nombre='Perfumes')
        cls.bodeguero = _crear_user(
            'bod', 'bodeguero', perms=['view_stocktienda', 'change_producto'],
        )
        cls.p1 = Producto.objects.create(
            familia=cls.fam, nombre='Perfume Yara',
            precio_base=Decimal('20000'), tiene_variantes=False,
        )
        cls.p2 = Producto.objects.create(
            familia=cls.fam, nombre='Perfume Oud',
            precio_base=Decimal('30000'), tiene_variantes=False,
        )

    def setUp(self):
        self.client.force_login(self.bodeguero)

    def test_htmx_devuelve_solo_tabla(self):
        resp = self.client.get(
            reverse('bodega:lista_productos'),
            HTTP_HX_REQUEST='true',
        )
        body = resp.content.decode()
        self.assertNotIn('<html', body.lower())
        self.assertIn('id="productos-tabla"', body)
        self.assertIn('Perfume Yara', body)

    def test_htmx_filtro_busca(self):
        resp = self.client.get(
            reverse('bodega:lista_productos') + '?q=Yara',
            HTTP_HX_REQUEST='true',
        )
        body = resp.content.decode()
        self.assertIn('Perfume Yara', body)
        self.assertNotIn('Perfume Oud', body)

    def test_sin_htmx_devuelve_pagina_completa(self):
        resp = self.client.get(reverse('bodega:lista_productos'))
        body = resp.content.decode()
        self.assertIn('<html', body.lower())


class OfertasListaAjaxTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = _crear_user('adm', 'admin')
        cls.fam = Familia.objects.create(nombre='Perfumes')
        cls.producto = Producto.objects.create(
            familia=cls.fam, nombre='Test',
            precio_base=Decimal('10000'), tiene_variantes=False,
        )
        ahora = timezone.now()
        Oferta.objects.create(
            nombre='Promo Verano', producto=cls.producto,
            tipo=Oferta.TIPO_PORCENTAJE, valor=Decimal('10'),
            canal=Oferta.CANAL_AMBOS,
            fecha_inicio=ahora - timedelta(days=1),
            fecha_fin=ahora + timedelta(days=5),
            activa=True,
        )
        Oferta.objects.create(
            nombre='Promo Invierno', producto=cls.producto,
            tipo=Oferta.TIPO_PORCENTAJE, valor=Decimal('20'),
            canal=Oferta.CANAL_AMBOS,
            fecha_inicio=ahora + timedelta(days=10),
            fecha_fin=ahora + timedelta(days=20),
            activa=True,
        )

    def setUp(self):
        self.client.force_login(self.admin)

    def test_htmx_devuelve_solo_tabla(self):
        resp = self.client.get(
            reverse('bodega:lista_ofertas'),
            HTTP_HX_REQUEST='true',
        )
        body = resp.content.decode()
        self.assertNotIn('<html', body.lower())
        self.assertIn('id="ofertas-tabla"', body)
        self.assertIn('Promo Verano', body)

    def test_htmx_filtro_busca(self):
        resp = self.client.get(
            reverse('bodega:lista_ofertas') + '?q=Verano',
            HTTP_HX_REQUEST='true',
        )
        body = resp.content.decode()
        self.assertIn('Promo Verano', body)
        self.assertNotIn('Promo Invierno', body)


class MaterialesListaAjaxTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.bodeguero = _crear_user(
            'bod', 'bodeguero', perms=['view_stocktienda'],
        )
        Material.objects.create(nombre='Casimir Garib azul')
        Material.objects.create(nombre='Tela franela silvia')

    def setUp(self):
        self.client.force_login(self.bodeguero)

    def test_htmx_devuelve_solo_tabla(self):
        resp = self.client.get(
            reverse('bodega:lista_materiales'),
            HTTP_HX_REQUEST='true',
        )
        body = resp.content.decode()
        self.assertNotIn('<html', body.lower())
        self.assertIn('id="materiales-tabla"', body)
        self.assertIn('Casimir Garib', body)

    def test_htmx_filtro_busca(self):
        resp = self.client.get(
            reverse('bodega:lista_materiales') + '?q=casimir',
            HTTP_HX_REQUEST='true',
        )
        body = resp.content.decode()
        self.assertIn('Casimir Garib', body)
        self.assertNotIn('franela silvia', body)
