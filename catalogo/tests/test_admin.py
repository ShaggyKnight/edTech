"""Tests del admin de catálogo (Fase D admin polish + Fase G).

Verifica que el admin renderiza con fieldsets, thumbnails y búsqueda
correctos, y que el formulario de Producto puede crear/editar sin errores.
"""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from catalogo.admin import ProductoAdmin
from catalogo.models import Familia, Producto


class ProductoAdminThumbsTests(TestCase):
    """Pruebas unitarias de los métodos `thumb` y `preview` del admin."""

    @classmethod
    def setUpTestData(cls):
        cls.familia = Familia.objects.create(nombre='Perfumes')

    def _admin(self):
        from django.contrib.admin.sites import AdminSite
        return ProductoAdmin(Producto, AdminSite())

    def test_thumb_sin_imagen_devuelve_dash(self):
        p = Producto.objects.create(
            familia=self.familia, nombre='X', precio_base=Decimal('1000'),
        )
        self.assertEqual(self._admin().thumb(p), '—')

    def test_preview_sin_imagen_avisa(self):
        p = Producto.objects.create(
            familia=self.familia, nombre='Y', precio_base=Decimal('1000'),
        )
        self.assertEqual(self._admin().preview(p), 'Sin imagen')

    def test_thumb_con_imagen_devuelve_html(self):
        """Cuando hay imagen, devolvemos un <img> con la URL."""
        p = Producto.objects.create(
            familia=self.familia, nombre='Z', precio_base=Decimal('1000'),
        )
        # Simulamos un FieldFile que evalúa truthy y expone .url.
        class _FakeImg:
            url = '/media/productos/foo.jpg'
            def __bool__(self): return True
        p.imagen = _FakeImg()

        html = self._admin().thumb(p)
        self.assertIn('<img', str(html))
        self.assertIn('/media/productos/foo.jpg', str(html))


class ProductoAdminVistaTests(TestCase):
    """Smoke tests: el admin de Producto se carga sin errores."""

    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.admin_user = User.objects.create_superuser(
            username='root', email='r@x.cl', password='Abc12345!',
        )
        cls.familia = Familia.objects.create(nombre='Perfumes')
        cls.producto = Producto.objects.create(
            familia=cls.familia, nombre='Perfume 30ml',
            precio_base=Decimal('12000'), precio_costo=Decimal('5000'),
            tiene_variantes=False,
        )

    def setUp(self):
        self.client.force_login(self.admin_user)

    def test_changelist_lista_thumb_y_nombre(self):
        resp = self.client.get(reverse('admin:catalogo_producto_changelist'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Perfume 30ml')

    def test_change_view_renderiza_fieldsets(self):
        """Los fieldsets de Fase D deben aparecer como <h2> en el form."""
        resp = self.client.get(
            reverse('admin:catalogo_producto_change', args=[self.producto.pk])
        )
        self.assertEqual(resp.status_code, 200)
        # Cada fieldset usa el título como cabecera. Verificamos los 3 nuevos.
        for titulo in ('Precios', 'Imagen', 'Variantes'):
            self.assertContains(resp, titulo)
        # El campo readonly `preview` debe estar presente como "Sin imagen".
        self.assertContains(resp, 'Sin imagen')

    def test_busqueda_por_nombre(self):
        Producto.objects.create(
            familia=self.familia, nombre='Otro perfume',
            precio_base=Decimal('8000'),
        )
        resp = self.client.get(
            reverse('admin:catalogo_producto_changelist') + '?q=Perfume+30'
        )
        self.assertContains(resp, 'Perfume 30ml')
        self.assertNotContains(resp, 'Otro perfume')
