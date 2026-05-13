"""Tests del flujo de etiquetas: seleccion + imprimir."""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.test import TestCase
from django.urls import reverse

from catalogo.barcode import generar_codigo_interno
from catalogo.models import Familia, Producto, ProductoVariante

User = get_user_model()


class EtiquetasTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.fam = Familia.objects.create(nombre='Uniformes')
        cls.bodeguero = User.objects.create_user('bod', password='x')
        g, _ = Group.objects.get_or_create(name='bodeguero')
        cls.bodeguero.groups.add(g)
        cls.bodeguero.user_permissions.add(
            Permission.objects.get(codename='view_stocktienda'),
            Permission.objects.get(codename='change_producto'),
        )

        # Producto sin variantes + codigo.
        cls.perfume = Producto.objects.create(
            familia=cls.fam, nombre='Perfume X',
            precio_base=Decimal('20000'), tiene_variantes=False,
        )
        cls.perfume.codigo_barras = generar_codigo_interno('p', cls.perfume.pk)
        cls.perfume.save()

        # Producto con variantes — codigo en la variante.
        cls.buzo = Producto.objects.create(
            familia=cls.fam, nombre='Buzo X',
            precio_base=Decimal('30000'), tiene_variantes=True,
        )
        cls.var = ProductoVariante.objects.create(producto=cls.buzo, sku='BX-M')
        cls.var.codigo_barras = generar_codigo_interno('v', cls.var.pk)
        cls.var.save()

        # Producto sin codigo (no aparece en la vista de imprimir).
        cls.sin_codigo = Producto.objects.create(
            familia=cls.fam, nombre='Sin codigo aun',
            precio_base=Decimal('5000'), tiene_variantes=False,
            codigo_barras=None,
        )

    def setUp(self):
        self.client.force_login(self.bodeguero)

    def test_pantalla_seleccion_lista_items_con_codigo(self):
        resp = self.client.get(reverse('bodega:etiquetas_seleccionar'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Perfume X')
        self.assertContains(resp, 'Buzo X')
        # El producto sin codigo aparece pero con advertencia.
        self.assertContains(resp, 'Sin codigo aun')
        self.assertContains(resp, 'Sin código')

    def test_filtro_por_familia(self):
        otra = Familia.objects.create(nombre='Perfumes')
        Producto.objects.create(
            familia=otra, nombre='Solo Perfume',
            precio_base=Decimal('10000'), tiene_variantes=False,
            codigo_barras='2009000000016',
        )
        resp = self.client.get(
            reverse('bodega:etiquetas_seleccionar') + f'?familia={otra.pk}'
        )
        self.assertContains(resp, 'Solo Perfume')
        self.assertNotContains(resp, 'Perfume X')

    def test_imprimir_renderiza_etiquetas_con_svg(self):
        resp = self.client.post(reverse('bodega:etiquetas_imprimir'), {
            f'p_{self.perfume.pk}': '2',  # 2 copias del producto
            f'v_{self.var.pk}': '3',      # 3 copias de la variante
        })
        self.assertEqual(resp.status_code, 200)
        # 2 + 3 = 5 etiquetas.
        self.assertEqual(resp.context['total'], 5)
        self.assertContains(resp, 'Perfume X')
        self.assertContains(resp, 'Buzo X')
        # Cada etiqueta lleva un <svg> con el codigo.
        self.assertContains(resp, '<svg')
        # El boton Imprimir aparece para que el bodeguero use Ctrl+P.
        self.assertContains(resp, 'window.print()')

    def test_imprimir_agrupa_30_por_hoja(self):
        resp = self.client.post(reverse('bodega:etiquetas_imprimir'), {
            f'v_{self.var.pk}': '60',  # 2 hojas justas
        })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['total'], 60)
        self.assertEqual(resp.context['total_hojas'], 2)

    def test_imprimir_sin_seleccion_redirige(self):
        resp = self.client.post(reverse('bodega:etiquetas_imprimir'), {})
        self.assertEqual(resp.status_code, 302)

    def test_imprimir_ignora_cantidad_invalida(self):
        resp = self.client.post(reverse('bodega:etiquetas_imprimir'), {
            f'p_{self.perfume.pk}': '0',
            f'v_{self.var.pk}': 'abc',
        })
        # Nada valido → redirige.
        self.assertEqual(resp.status_code, 302)

    def test_imprimir_ignora_items_sin_codigo(self):
        resp = self.client.post(reverse('bodega:etiquetas_imprimir'), {
            f'p_{self.sin_codigo.pk}': '5',
        })
        self.assertEqual(resp.status_code, 302)

    def test_cajero_no_accede(self):
        cajero = User.objects.create_user('caj', password='x')
        g, _ = Group.objects.get_or_create(name='cajero')
        cajero.groups.add(g)
        self.client.force_login(cajero)
        resp = self.client.get(reverse('bodega:etiquetas_seleccionar'))
        self.assertEqual(resp.status_code, 302)

    def test_imprimir_solo_acepta_post(self):
        resp = self.client.get(reverse('bodega:etiquetas_imprimir'))
        self.assertEqual(resp.status_code, 405)
