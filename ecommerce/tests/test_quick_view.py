"""Tests del endpoint quick-view: fragment para el modal "Vista rápida"
desde la card del catálogo."""
from decimal import Decimal

from django.test import TestCase, override_settings
from django.urls import reverse

from bodega.models import StockTienda, Tienda
from catalogo.models import (
    Atributo, Familia, Producto, ProductoVariante, ValorAtributo,
)


@override_settings(ECOMMERCE_PAYMENT_GATEWAY='mock')
class QuickViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tienda = Tienda.objects.create(nombre_organizacion='Online', activa=True)
        cls.fam = Familia.objects.create(nombre='Perfumes')

        cls.producto = Producto.objects.create(
            familia=cls.fam, nombre='Perfume Quick',
            descripcion='Notas frescas, cítricos y madera.',
            precio_base=Decimal('20000'), tiene_variantes=False,
        )
        StockTienda.objects.create(tienda=cls.tienda, producto=cls.producto, cantidad=5)

        cls.fam_uni = Familia.objects.create(nombre='Uniformes')
        cls.con_variantes = Producto.objects.create(
            familia=cls.fam_uni, nombre='Buzo Quick',
            precio_base=Decimal('30000'), tiene_variantes=True,
        )
        cls.atr = Atributo.objects.create(nombre='Talla')
        cls.val_m = ValorAtributo.objects.create(atributo=cls.atr, valor='M', orden=2)
        cls.var_m = ProductoVariante.objects.create(producto=cls.con_variantes, sku='BZ-M')
        cls.var_m.valores.add(cls.val_m)
        StockTienda.objects.create(tienda=cls.tienda, variante=cls.var_m, cantidad=3)

        cls.inactivo = Producto.objects.create(
            familia=cls.fam, nombre='Inactivo',
            precio_base=Decimal('5000'), tiene_variantes=False, activo=False,
        )

    def setUp(self):
        self.settings_override = self.settings(ECOMMERCE_TIENDA_ID=self.tienda.pk)
        self.settings_override.enable()

    def tearDown(self):
        self.settings_override.disable()

    def test_devuelve_fragment_no_pagina_completa(self):
        resp = self.client.get(reverse('ecommerce:producto_quick', args=[self.producto.pk]))
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode().lower()
        # No es una pagina completa.
        self.assertNotIn('<html', body)
        self.assertNotIn('<head', body)
        # Si trae el contenido del modal.
        self.assertIn('quick-view-content', body)

    def test_contiene_datos_basicos_del_producto(self):
        resp = self.client.get(reverse('ecommerce:producto_quick', args=[self.producto.pk]))
        body = resp.content.decode()
        self.assertIn('Perfume Quick', body)
        self.assertIn('Notas frescas', body)
        self.assertIn('Perfumes', body)  # familia
        # Precio formateado.
        self.assertIn('20.000', body)

    def test_producto_sin_variantes_muestra_form_agregar(self):
        resp = self.client.get(reverse('ecommerce:producto_quick', args=[self.producto.pk]))
        body = resp.content.decode()
        # Tiene form HTMX para agregar directo desde el modal.
        self.assertIn('hx-post="/tienda/agregar/"', body)
        self.assertIn('Agregar al carrito', body)

    def test_producto_con_variantes_permite_agregar_desde_modal(self):
        """Mejora: el modal Vista rápida YA permite elegir talla y agregar
        sin tener que ir a la PDP completa. Los chips son botones
        clickeables que setean el `<input name=item_id>` del form HTMX
        de agregar, que arranca disabled hasta que se elige una talla.
        """
        resp = self.client.get(reverse('ecommerce:producto_quick', args=[self.con_variantes.pk]))
        body = resp.content.decode()

        # Tiene form HTMX inline de agregar (no solo link a PDP).
        self.assertIn('hx-post="/tienda/agregar/"', body)
        self.assertIn('id="qv-agregar-form"', body)
        # `tipo=v` porque agrega una VARIANTE específica.
        self.assertIn('name="tipo" value="v"', body)

        # Los chips son botones clickeables con data-variante-id.
        self.assertIn('<button type="button"', body)
        self.assertIn('data-variante-id=', body)
        self.assertIn('onclick="qvSeleccionar(this)"', body)

        # El botón arranca disabled con copy explicito.
        self.assertIn('id="qv-agregar-btn"', body)
        self.assertIn('disabled', body)
        self.assertIn('Elegí una talla primero', body)

        # El handler global qvSeleccionar esta definido.
        self.assertIn('window.qvSeleccionar', body)

        # Link "Ver detalle completo" se mantiene como secundario.
        self.assertIn('Ver detalle completo', body)

    def test_link_a_pdp_completo(self):
        resp = self.client.get(reverse('ecommerce:producto_quick', args=[self.producto.pk]))
        body = resp.content.decode()
        url_pdp = reverse('ecommerce:producto', args=[self.producto.pk])
        self.assertIn(f'href="{url_pdp}"', body)
        self.assertIn('Ver detalle completo', body)

    def test_producto_inexistente_404(self):
        resp = self.client.get(reverse('ecommerce:producto_quick', args=[999999]))
        self.assertEqual(resp.status_code, 404)

    def test_producto_inactivo_404(self):
        resp = self.client.get(reverse('ecommerce:producto_quick', args=[self.inactivo.pk]))
        self.assertEqual(resp.status_code, 404)

    def test_solo_acepta_get(self):
        resp = self.client.post(reverse('ecommerce:producto_quick', args=[self.producto.pk]))
        self.assertEqual(resp.status_code, 405)

    def test_variantes_ordenadas_por_talla_canonica(self):
        """BUG-014 regression guard.

        El modal antes ordenaba por SKU (alfabético): L, M, S, XL. Ahora
        debe respetar el `orden` canónico de ValorAtributo: S, M, L, XL.
        """
        # Producto con 4 tallas en orden canónico. `val_m` ya existe en
        # setUpTestData; las otras 3 las creamos acá. El unique
        # (atributo, valor) impide re-crearlas.
        prod = Producto.objects.create(
            familia=self.fam_uni, nombre='Polera Test',
            precio_base=Decimal('15000'), tiene_variantes=True,
        )
        val_s = ValorAtributo.objects.create(atributo=self.atr, valor='S', orden=1)
        val_l = ValorAtributo.objects.create(atributo=self.atr, valor='L', orden=3)
        val_xl = ValorAtributo.objects.create(atributo=self.atr, valor='XL', orden=4)
        # Crear los SKUs en orden inverso alfabético para confirmar
        # que NO se está ordenando por SKU.
        for val, sku in [(val_xl, 'POL-XL'), (val_s, 'POL-S'),
                         (val_l, 'POL-L'), (self.val_m, 'POL-M')]:
            v = ProductoVariante.objects.create(producto=prod, sku=sku)
            v.valores.add(val)
            StockTienda.objects.create(tienda=self.tienda, variante=v, cantidad=5)

        resp = self.client.get(reverse('ecommerce:producto_quick', args=[prod.pk]))
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()

        # Limitamos la búsqueda al bloque de las variantes (size-chip)
        # para no falsos positivos con la 'S' / 'M' en el copy del modal.
        bloque_inicio = body.find('quick-view-variantes')
        bloque_fin = body.find('quick-view-ctas')
        bloque = body[bloque_inicio:bloque_fin]

        # Las tallas deben aparecer en el orden S, M, L, XL (no por SKU).
        # XL se busca primero para evitar que 'L' lo matche dentro de 'XL'.
        idx_s = bloque.find('>\n                S')
        idx_m = bloque.find('>\n                M')
        idx_l = bloque.find('>\n                L\n')
        idx_xl = bloque.find('>\n                XL')
        self.assertTrue(idx_s < idx_m < idx_l < idx_xl,
            f'BUG-014: tallas deben ir S,M,L,XL. '
            f'indices encontrados: S={idx_s}, M={idx_m}, L={idx_l}, XL={idx_xl}')

    def test_card_del_catalogo_incluye_boton_quick(self):
        """La card del catalogo tiene el boton que dispara el modal."""
        resp = self.client.get(reverse('ecommerce:catalogo'))
        body = resp.content.decode()
        self.assertIn('pcard-quick', body)
        self.assertIn('hx-target="#quick-view-body"', body)
