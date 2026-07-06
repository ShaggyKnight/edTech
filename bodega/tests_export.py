"""Exportacion de listados (productos / stock) a CSV con filtros aplicados."""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse

from accounts.roles import BODEGUERO, OPERADOR
from bodega.models import StockTienda, Tienda
from catalogo.models import Familia, Producto

User = get_user_model()


def _csv_texto(resp):
    """Decodifica el cuerpo del CSV (sin el BOM) para asserts de contenido."""
    return resp.content.decode('utf-8-sig')


def _filas(resp):
    """Filas no vacias del CSV, sin encabezado."""
    lineas = [l for l in _csv_texto(resp).splitlines() if l.strip()]
    return lineas[1:]


class ExportProductosTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.perfumes = Familia.objects.create(nombre='Perfumes')
        cls.buzos = Familia.objects.create(nombre='Buzos')
        cls.p1 = Producto.objects.create(
            familia=cls.perfumes, nombre='Yara Lattafa',
            marca='Lattafa', precio_base=Decimal('19990'),
            precio_costo=Decimal('9000'), tiene_variantes=False,
        )
        cls.p2 = Producto.objects.create(
            familia=cls.buzos, nombre='Buzo SFJ',
            precio_base=Decimal('25990'), tiene_variantes=False,
        )
        cls.admin = User.objects.create_superuser('admin', password='x')
        cls.bodeguero = User.objects.create_user('bodega', password='x')
        cls.bodeguero.groups.add(Group.objects.get(name=BODEGUERO))

    def test_descarga_csv_con_content_disposition_y_bom(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse('bodega:exportar_productos'))
        self.assertEqual(resp.status_code, 200)
        self.assertIn('text/csv', resp['Content-Type'])
        self.assertIn('attachment; filename="productos_', resp['Content-Disposition'])
        # BOM UTF-8 al inicio para que Excel es-CL lo abra bien.
        self.assertTrue(resp.content.startswith(b'\xef\xbb\xbf'))
        # Separador ';' (Excel chileno).
        self.assertIn(b';', resp.content)

    def test_incluye_todos_los_productos_sin_filtro(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse('bodega:exportar_productos'))
        cuerpo = _csv_texto(resp)
        self.assertIn('Yara Lattafa', cuerpo)
        self.assertIn('Buzo SFJ', cuerpo)
        self.assertEqual(len(_filas(resp)), 2)

    def test_respeta_filtro_de_familia(self):
        self.client.force_login(self.admin)
        resp = self.client.get(
            reverse('bodega:exportar_productos') + f'?familia={self.perfumes.pk}'
        )
        cuerpo = _csv_texto(resp)
        self.assertIn('Yara Lattafa', cuerpo)
        self.assertNotIn('Buzo SFJ', cuerpo)
        self.assertEqual(len(_filas(resp)), 1)

    def test_respeta_busqueda_por_texto(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse('bodega:exportar_productos') + '?q=yara')
        self.assertIn('Yara Lattafa', _csv_texto(resp))
        self.assertNotIn('Buzo SFJ', _csv_texto(resp))

    def test_admin_ve_columna_costo(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse('bodega:exportar_productos'))
        cuerpo = _csv_texto(resp)
        self.assertIn('Precio costo', cuerpo)
        self.assertIn('9000', cuerpo)   # el costo del perfume

    def test_bodeguero_no_ve_columna_costo(self):
        """El costo es margen: solo admin/operador. El CSV no debe
        filtrar mas de lo que el rol ve en pantalla."""
        self.client.force_login(self.bodeguero)
        resp = self.client.get(reverse('bodega:exportar_productos'))
        cuerpo = _csv_texto(resp)
        self.assertNotIn('Precio costo', cuerpo)
        self.assertNotIn('9000', cuerpo)
        # Pero SI ve los productos (precio de venta incluido).
        self.assertIn('Yara Lattafa', cuerpo)

    def test_anonimo_redirige_a_login(self):
        resp = self.client.get(reverse('bodega:exportar_productos'))
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/cuenta/login', resp['Location'])


class ExportStockTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.tienda = Tienda.objects.create(nombre_organizacion='Central', activa=True)
        # Perfumes con umbral 0: 1-2 unidades es stock NORMAL (ver
        # migracion 0012 / tests_umbral_stock). En el test lo seteamos
        # explicito porque la familia se crea aca, post-migracion.
        fam = Familia.objects.create(nombre='Perfumes', umbral_stock_bajo=0)
        cls.perfume = Producto.objects.create(
            familia=fam, nombre='Perfume A',
            precio_base=Decimal('19990'), tiene_variantes=False,
        )
        StockTienda.objects.create(tienda=cls.tienda, producto=cls.perfume, cantidad=2)
        cls.operador = User.objects.create_user('blanca', password='x')
        cls.operador.groups.add(Group.objects.get(name=OPERADOR))

    def test_descarga_csv_de_stock(self):
        self.client.force_login(self.operador)
        resp = self.client.get(reverse('bodega:exportar_stock') + '?solo=todos')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('attachment; filename="stock_', resp['Content-Disposition'])
        cuerpo = resp.content.decode('utf-8-sig')
        self.assertIn('Perfume A', cuerpo)
        self.assertIn('Central', cuerpo)
        # 2 unidades con umbral de perfumes → estado OK, no "Bajo".
        self.assertIn('OK', cuerpo)

    def test_respeta_filtro_solo_agotados(self):
        self.client.force_login(self.operador)
        resp = self.client.get(reverse('bodega:exportar_stock') + '?solo=cero')
        cuerpo = resp.content.decode('utf-8-sig')
        # El unico item tiene 2 unidades → no aparece en "solo agotados".
        self.assertNotIn('Perfume A', cuerpo)

    def test_anonimo_redirige(self):
        resp = self.client.get(reverse('bodega:exportar_stock'))
        self.assertEqual(resp.status_code, 302)
