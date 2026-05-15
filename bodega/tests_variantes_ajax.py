"""Bloque 16: tests de los filtros AJAX en la lista de variantes."""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.test import TestCase
from django.urls import reverse

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


class VariantesFiltrosAJAXTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.fam = Familia.objects.create(nombre='Buzos')
        cls.producto = Producto.objects.create(
            familia=cls.fam, nombre='Buzo SFJ',
            precio_base=Decimal('20000'), tiene_variantes=True,
        )

        cls.atr_talla = Atributo.objects.create(nombre='Talla')
        cls.val_10 = ValorAtributo.objects.create(
            atributo=cls.atr_talla, valor='10', orden=4,
        )
        cls.val_12 = ValorAtributo.objects.create(
            atributo=cls.atr_talla, valor='12', orden=5,
        )
        cls.val_M = ValorAtributo.objects.create(
            atributo=cls.atr_talla, valor='M', orden=8,
        )

        cls.v10 = ProductoVariante.objects.create(
            producto=cls.producto, sku='BZ-SFJ-10', activa=True,
        )
        cls.v10.valores.add(cls.val_10)

        cls.v12 = ProductoVariante.objects.create(
            producto=cls.producto, sku='BZ-SFJ-12', activa=True,
        )
        cls.v12.valores.add(cls.val_12)

        cls.vm = ProductoVariante.objects.create(
            producto=cls.producto, sku='BZ-SFJ-M', activa=False,
        )
        cls.vm.valores.add(cls.val_M)

        cls.bodeguero = _crear_user('bod', 'bodeguero', perms=['view_stocktienda'])
        cls.url = reverse('bodega:variantes', args=[cls.producto.pk])

    def setUp(self):
        self.client.force_login(self.bodeguero)

    def test_lista_sin_filtros_muestra_todas(self):
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'BZ-SFJ-10')
        self.assertContains(r, 'BZ-SFJ-12')
        self.assertContains(r, 'BZ-SFJ-M')

    def test_filtro_q_por_sku(self):
        r = self.client.get(self.url, {'q': 'SFJ-10'})
        self.assertContains(r, 'BZ-SFJ-10')
        self.assertNotContains(r, 'BZ-SFJ-12')

    def test_filtro_q_por_valor_atributo(self):
        """Buscar '12' debe encontrar la variante con talla 12."""
        r = self.client.get(self.url, {'q': '12'})
        self.assertContains(r, 'BZ-SFJ-12')
        self.assertNotContains(r, 'BZ-SFJ-10')

    def test_filtro_estado_activas(self):
        r = self.client.get(self.url, {'estado': 'activas'})
        self.assertContains(r, 'BZ-SFJ-10')
        self.assertContains(r, 'BZ-SFJ-12')
        self.assertNotContains(r, 'BZ-SFJ-M')

    def test_filtro_estado_inactivas(self):
        r = self.client.get(self.url, {'estado': 'inactivas'})
        self.assertContains(r, 'BZ-SFJ-M')
        self.assertNotContains(r, 'BZ-SFJ-10')
        self.assertNotContains(r, 'BZ-SFJ-12')

    def test_htmx_devuelve_solo_la_tabla(self):
        r = self.client.get(self.url, HTTP_HX_REQUEST='true')
        self.assertEqual(r.status_code, 200)
        # El partial NO incluye el header de la pagina, solo la tabla.
        self.assertContains(r, 'variantes-tabla')
        self.assertNotContains(r, '<h1>Variantes')

    def test_sin_htmx_devuelve_pagina_completa(self):
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 200)
        # La pagina completa incluye el header.
        self.assertContains(r, '<h1>Variantes')
        # Y el form de filtros.
        self.assertContains(r, 'name="q"')
        self.assertContains(r, 'name="estado"')

    def test_filtro_combinado_q_y_estado(self):
        """q='12' + estado='activas' → solo BZ-SFJ-12 (activa con valor 12)."""
        r = self.client.get(self.url, {'q': '12', 'estado': 'activas'})
        self.assertContains(r, 'BZ-SFJ-12')
        self.assertNotContains(r, 'BZ-SFJ-M')

    def test_filtro_sin_matches_muestra_empty(self):
        r = self.client.get(self.url, {'q': 'xyz-nonexistent'})
        self.assertContains(r, 'No hay variantes que matcheen los filtros')

    def test_contador_filtradas_vs_total(self):
        """El header muestra `N de M variantes` cuando hay filtros."""
        r = self.client.get(self.url, {'estado': 'activas'})
        # 2 de 3.
        self.assertContains(r, '2 of 3' if False else '2 de 3')
