"""Tests del scroll infinito del catalogo (HTMX + paginacion)."""
from decimal import Decimal

from django.test import TestCase, override_settings
from django.urls import reverse

from bodega.models import StockTienda, Tienda
from catalogo.models import Familia, Producto


@override_settings(ECOMMERCE_PAYMENT_GATEWAY='mock')
class ScrollInfinitoTests(TestCase):
    """Verifica que la paginacion via HTMX devuelva fragments y no
    paginas enteras, y que el sentinel aparezca solo si hay mas datos."""

    @classmethod
    def setUpTestData(cls):
        cls.tienda = Tienda.objects.create(nombre_organizacion='Online', activa=True)
        cls.fam = Familia.objects.create(nombre='Perfumes')
        # Crear 15 productos con stock — supera el PAGE_SIZE (12) para
        # forzar 2 paginas.
        cls.productos = []
        for i in range(15):
            p = Producto.objects.create(
                familia=cls.fam, nombre=f'Producto {i:02d}',
                precio_base=Decimal('10000') + i,
                tiene_variantes=False,
            )
            StockTienda.objects.create(tienda=cls.tienda, producto=p, cantidad=3)
            cls.productos.append(p)

    def setUp(self):
        self.settings_override = self.settings(ECOMMERCE_TIENDA_ID=self.tienda.pk)
        self.settings_override.enable()

    def tearDown(self):
        self.settings_override.disable()

    def test_pagina_uno_incluye_sentinel(self):
        """Si hay mas productos despues del PAGE_SIZE, la pagina 1
        renderiza el sentinel para que HTMX cargue la siguiente."""
        resp = self.client.get(reverse('ecommerce:catalogo'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'shop-grid-loader')
        self.assertContains(resp, 'page=2')

    def test_pagina_uno_sin_paginacion_si_pocos_productos(self):
        """Con pocos productos no debe aparecer el sentinel."""
        # Filtro a un nombre que solo matchea un producto — usar `q` evita
        # tener que tocar la DB compartida del setUpTestData.
        resp = self.client.get(reverse('ecommerce:catalogo') + '?q=Producto+00')
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'shop-grid-loader')

    def test_pagina_dos_no_tiene_sentinel_si_es_ultima(self):
        resp = self.client.get(reverse('ecommerce:catalogo') + '?page=2')
        self.assertEqual(resp.status_code, 200)
        # La pagina 2 con 15 productos y PAGE_SIZE=12 trae los 3 ultimos
        # y no necesita sentinel.
        self.assertNotContains(resp, 'shop-grid-loader')

    def test_htmx_pagina_dos_devuelve_fragment_sin_layout(self):
        """Si el header HX-Request esta presente y page > 1, devolver
        solo el fragment con cards, sin <html>, <head>, layout, etc."""
        resp = self.client.get(
            reverse('ecommerce:catalogo') + '?page=2',
            HTTP_HX_REQUEST='true',
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode().lower()
        self.assertNotIn('<html', body)
        self.assertNotIn('<head', body)
        self.assertNotIn('shop-filters-form', body)
        # Pero si trae los productos.
        self.assertIn('pcard', body)

    def test_htmx_pagina_uno_devuelve_layout_completo(self):
        """Para la primera carga (incluso desde HTMX), devolvemos la
        pagina completa para que el layout exista."""
        resp = self.client.get(
            reverse('ecommerce:catalogo'),
            HTTP_HX_REQUEST='true',
        )
        body = resp.content.decode().lower()
        self.assertIn('<html', body)

    def test_paginacion_preserva_filtros_en_url_del_sentinel(self):
        """El sentinel debe llevar los filtros activos en la URL para
        que la siguiente pagina respete categoria, talla, etc."""
        resp = self.client.get(
            reverse('ecommerce:catalogo') + '?cat=perfumes'
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'cat=perfumes')
        self.assertContains(resp, 'page=2')

    def test_total_productos_refleja_todo_no_solo_pagina(self):
        """El contador del header muestra el total real, no la pagina."""
        resp = self.client.get(reverse('ecommerce:catalogo'))
        self.assertContains(resp, '15 producto')
