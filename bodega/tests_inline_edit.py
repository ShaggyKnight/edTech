"""Regresion: edicion inline de precio/estado en la lista de productos.

Bug historico: la tabla iba envuelta en un <form> de bulk, y las celdas
de precio/estado tenian su propio <form> adentro. Los <form> anidados el
navegador los elimina (HTML invalido) → el precio no guardaba y el toggle
disparaba el form equivocado. Ademas, al postear una celda desde dentro
del form de bulk, HTMX arrastraba los 174 inputs `precio_base` y Django se
quedaba con el ultimo (editaba el producto equivocado).

Fix: la tabla ya NO es un <form>; celdas y bulk postean via HTMX sin form.
Estos tests fijan la estructura para que no reaparezca.
"""
import re
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from catalogo.models import Familia, Producto

User = get_user_model()


class ProductosListaSinFormsAnidadosTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.fam = Familia.objects.create(nombre='Perfumes')
        cls.p = Producto.objects.create(
            familia=cls.fam, nombre='Perfume Uno',
            precio_base=Decimal('19990'), tiene_variantes=False,
        )
        cls.admin = User.objects.create_superuser('admin', password='x')

    def setUp(self):
        self.client.force_login(self.admin)

    def _html(self):
        resp = self.client.get(reverse('bodega:lista_productos'))
        self.assertEqual(resp.status_code, 200)
        return resp.content.decode()

    def test_no_hay_form_de_bulk_envolviendo_la_tabla(self):
        html = self._html()
        # El viejo <form id="bulk-productos-form"> ya no debe existir.
        self.assertNotIn('bulk-productos-form', html)

    def test_zona_de_tabla_no_contiene_ningun_form(self):
        """Dentro de #productos-tabla no debe haber <form> (forms anidados
        o de celda). Precio y estado postean via hx-post sin <form>."""
        html = self._html()
        tabla = html.split('id="productos-tabla"', 1)[1]
        # Quitar los <script> (un comentario JS menciona "<form>" en texto).
        tabla = re.sub(r'<script[\s\S]*?</script>', '', tabla)
        self.assertNotRegex(tabla, r'<form[\s>]')

    def test_celda_precio_usa_hx_post_no_form(self):
        html = self._html()
        self.assertIn(f'id="precio-input-{self.p.pk}"', html)
        self.assertIn(reverse('bodega:set_precio', args=[self.p.pk]), html)

    def test_celda_estado_es_boton_hx_post(self):
        html = self._html()
        # La celda de estado es un <button type="button" hx-post=...>.
        celda = html.split(f'id="activo-celda-{self.p.pk}"', 1)[1][:400]
        self.assertIn('hx-post', celda)
        self.assertNotIn('<form', celda)


class SetPrecioCsrfHeaderTests(TestCase):
    """set_precio/toggle deben funcionar con CSRF por header X-CSRFToken
    (las celdas ya no mandan el campo csrfmiddlewaretoken de un <form>)."""

    @classmethod
    def setUpTestData(cls):
        cls.fam = Familia.objects.create(nombre='Perfumes')
        cls.p = Producto.objects.create(
            familia=cls.fam, nombre='Perfume CSRF',
            precio_base=Decimal('10000'), tiene_variantes=False,
        )
        cls.admin = User.objects.create_superuser('admin', password='x')

    def test_set_precio_por_header_csrf(self):
        # Cliente que ENFORZA CSRF (el default exime; aca lo activamos).
        from django.test import Client
        c = Client(enforce_csrf_checks=True)
        c.force_login(self.admin)
        # Obtener el token del cookie (lo setea cualquier GET).
        c.get(reverse('bodega:lista_productos'))
        token = c.cookies['csrftoken'].value
        resp = c.post(
            reverse('bodega:set_precio', args=[self.p.pk]),
            {'precio_base': '15500'},
            HTTP_HX_REQUEST='true',
            HTTP_X_CSRFTOKEN=token,
        )
        self.assertEqual(resp.status_code, 200)
        self.p.refresh_from_db()
        self.assertEqual(self.p.precio_base, Decimal('15500'))

    def test_toggle_activo_por_header_csrf(self):
        from django.test import Client
        c = Client(enforce_csrf_checks=True)
        c.force_login(self.admin)
        c.get(reverse('bodega:lista_productos'))
        token = c.cookies['csrftoken'].value
        antes = self.p.activo
        resp = c.post(
            reverse('bodega:producto_toggle_activo', args=[self.p.pk]),
            HTTP_HX_REQUEST='true',
            HTTP_X_CSRFTOKEN=token,
        )
        self.assertEqual(resp.status_code, 200)
        self.p.refresh_from_db()
        self.assertEqual(self.p.activo, not antes)
