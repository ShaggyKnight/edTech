"""Bloque 15: tests del drag-drop de la galeria de producto.

Cubre: vista de listado, reorder (permisos + validaciones), borrar.
"""
from decimal import Decimal
from io import BytesIO

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.files.base import ContentFile
from django.test import TestCase
from django.urls import reverse

from catalogo.models import Familia, Producto, ProductoImagen

User = get_user_model()


def _imagen_dummy(name='dummy.jpg'):
    return ContentFile(
        b'\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00',
        name=name,
    )


def _crear_user(username, grupo=None, perms=()):
    u = User.objects.create_user(username, password='x')
    if grupo:
        g, _ = Group.objects.get_or_create(name=grupo)
        u.groups.add(g)
    for codename in perms:
        u.user_permissions.add(Permission.objects.get(codename=codename))
    return u


class GaleriaProductoTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.fam = Familia.objects.create(nombre='Perfumes')
        cls.producto = Producto.objects.create(
            familia=cls.fam, nombre='Yara',
            precio_base=Decimal('20000'),
        )
        # 3 imagenes con orden 0, 1, 2
        cls.img1 = ProductoImagen.objects.create(
            producto=cls.producto, imagen=_imagen_dummy('a.jpg'),
            orden=0, alt='Frontal',
        )
        cls.img2 = ProductoImagen.objects.create(
            producto=cls.producto, imagen=_imagen_dummy('b.jpg'),
            orden=1, alt='Lateral',
        )
        cls.img3 = ProductoImagen.objects.create(
            producto=cls.producto, imagen=_imagen_dummy('c.jpg'),
            orden=2, alt='Trasera',
        )

        # Otro producto con su imagen (para cross-product check)
        cls.otro = Producto.objects.create(
            familia=cls.fam, nombre='Otro',
            precio_base=Decimal('1000'),
        )
        cls.img_otro = ProductoImagen.objects.create(
            producto=cls.otro, imagen=_imagen_dummy('z.jpg'),
            orden=0,
        )

        cls.admin = _crear_user('adm', 'admin')
        cls.bodeguero = _crear_user('bod', 'bodeguero', perms=['view_stocktienda'])
        cls.cajero = _crear_user('caj', 'cajero')

    # ── Vista lista ────────────────────────────────────────────────

    def test_admin_ve_galeria(self):
        self.client.force_login(self.admin)
        url = reverse('bodega:galeria_producto', args=[self.producto.pk])
        r = self.client.get(url)
        self.assertEqual(r.status_code, 200)
        # 3 imagenes renderizadas con data-img-id
        self.assertContains(r, f'data-img-id="{self.img1.pk}"')
        self.assertContains(r, f'data-img-id="{self.img2.pk}"')
        self.assertContains(r, f'data-img-id="{self.img3.pk}"')
        # Puede reordenar (admin)
        self.assertContains(r, 'data-puede-reordenar="1"')

    def test_bodeguero_ve_galeria_pero_no_puede_reordenar(self):
        self.client.force_login(self.bodeguero)
        url = reverse('bodega:galeria_producto', args=[self.producto.pk])
        r = self.client.get(url)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'data-puede-reordenar="0"')

    def test_cajero_no_ve_galeria(self):
        """@reponer_required excluye cajeros."""
        self.client.force_login(self.cajero)
        url = reverse('bodega:galeria_producto', args=[self.producto.pk])
        r = self.client.get(url)
        self.assertEqual(r.status_code, 302)

    # ── Reorder ────────────────────────────────────────────────────

    def test_admin_reordena(self):
        self.client.force_login(self.admin)
        url = reverse('bodega:galeria_reorder', args=[self.producto.pk])
        # Nuevo orden: img3 primero, img1 segundo, img2 tercero
        resp = self.client.post(url, {
            'orden_ids': f'{self.img3.pk},{self.img1.pk},{self.img2.pk}',
        })
        self.assertEqual(resp.status_code, 302)
        self.img1.refresh_from_db()
        self.img2.refresh_from_db()
        self.img3.refresh_from_db()
        self.assertEqual(self.img3.orden, 0)
        self.assertEqual(self.img1.orden, 1)
        self.assertEqual(self.img2.orden, 2)

    def test_htmx_reorder_devuelve_ok(self):
        self.client.force_login(self.admin)
        url = reverse('bodega:galeria_reorder', args=[self.producto.pk])
        resp = self.client.post(
            url,
            {'orden_ids': f'{self.img2.pk},{self.img1.pk},{self.img3.pk}'},
            HTTP_HX_REQUEST='true',
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b'OK', resp.content)

    def test_bodeguero_no_puede_reordenar(self):
        self.client.force_login(self.bodeguero)
        url = reverse('bodega:galeria_reorder', args=[self.producto.pk])
        resp = self.client.post(url, {
            'orden_ids': f'{self.img3.pk},{self.img1.pk},{self.img2.pk}',
        })
        # 302 redirect con error message — NO actualiza.
        self.assertEqual(resp.status_code, 302)
        self.img1.refresh_from_db()
        self.assertEqual(self.img1.orden, 0)  # sin cambiar

    def test_htmx_bodeguero_403(self):
        self.client.force_login(self.bodeguero)
        url = reverse('bodega:galeria_reorder', args=[self.producto.pk])
        resp = self.client.post(
            url,
            {'orden_ids': f'{self.img3.pk}'},
            HTTP_HX_REQUEST='true',
        )
        self.assertEqual(resp.status_code, 403)

    def test_ids_de_otro_producto_son_rechazados(self):
        """No se puede reordenar imagen de otro producto via POST forjado."""
        self.client.force_login(self.admin)
        url = reverse('bodega:galeria_reorder', args=[self.producto.pk])
        resp = self.client.post(
            url,
            {'orden_ids': f'{self.img1.pk},{self.img_otro.pk}'},
            HTTP_HX_REQUEST='true',
        )
        self.assertEqual(resp.status_code, 400)
        self.img_otro.refresh_from_db()
        # No cambio.
        self.assertEqual(self.img_otro.orden, 0)

    def test_orden_invalido_400(self):
        self.client.force_login(self.admin)
        url = reverse('bodega:galeria_reorder', args=[self.producto.pk])
        resp = self.client.post(
            url, {'orden_ids': 'abc,xyz'}, HTTP_HX_REQUEST='true',
        )
        self.assertEqual(resp.status_code, 400)

    def test_sin_orden_400(self):
        self.client.force_login(self.admin)
        url = reverse('bodega:galeria_reorder', args=[self.producto.pk])
        resp = self.client.post(url, {}, HTTP_HX_REQUEST='true')
        self.assertEqual(resp.status_code, 400)

    # ── Borrar ─────────────────────────────────────────────────────

    def test_admin_borra_imagen(self):
        self.client.force_login(self.admin)
        url = reverse('bodega:galeria_borrar', args=[self.producto.pk, self.img2.pk])
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(ProductoImagen.objects.filter(pk=self.img2.pk).exists())

    def test_bodeguero_borra_imagen(self):
        """A diferencia del reorder, bodeguero SI puede borrar (mismo
        nivel que editar producto / gestionar stock)."""
        self.client.force_login(self.bodeguero)
        url = reverse('bodega:galeria_borrar', args=[self.producto.pk, self.img2.pk])
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(ProductoImagen.objects.filter(pk=self.img2.pk).exists())

    def test_no_se_puede_borrar_imagen_de_otro_producto_via_url(self):
        """Mezclando pk de producto con img_pk de otro producto → 404."""
        self.client.force_login(self.admin)
        url = reverse(
            'bodega:galeria_borrar',
            args=[self.producto.pk, self.img_otro.pk],
        )
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 404)
        self.assertTrue(ProductoImagen.objects.filter(pk=self.img_otro.pk).exists())
