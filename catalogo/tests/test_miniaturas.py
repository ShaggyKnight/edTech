"""Miniaturas WebP de las fotos de producto (catalogo/miniaturas.py)."""
import io
import shutil
import tempfile
from decimal import Decimal

from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from bodega.models import StockTienda, Tienda
from catalogo import miniaturas
from catalogo.models import Familia, Producto


def foto_png(ancho=1200, alto=1500):
    buffer = io.BytesIO()
    Image.new('RGB', (ancho, alto), (200, 30, 40)).save(buffer, 'PNG')
    return SimpleUploadedFile('buzo.png', buffer.getvalue(), content_type='image/png')


class MiniaturasTests(TestCase):

    def setUp(self):
        self.media = tempfile.mkdtemp()
        self.override = override_settings(MEDIA_ROOT=self.media)
        self.override.enable()
        self.tienda = Tienda.objects.create(nombre_organizacion='Online', activa=True)
        self.fam = Familia.objects.create(nombre='Uniformes Escolares')

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.media, ignore_errors=True)

    def crear_producto(self, **extra):
        p = Producto.objects.create(
            familia=self.fam, nombre='Buzo', precio_base=Decimal('20000'),
            tiene_variantes=False, imagen=foto_png(), **extra,
        )
        p.refresh_from_db()
        return p

    def test_se_generan_al_guardar(self):
        p = self.crear_producto()
        for ancho in miniaturas.ANCHOS:
            nombre = miniaturas.nombre_miniatura(p.imagen.name, ancho)
            self.assertTrue(default_storage.exists(nombre), nombre)
            with default_storage.open(nombre, 'rb') as f, Image.open(f) as im:
                self.assertEqual(im.format, 'WEBP')
                self.assertEqual(im.width, ancho)

    def test_srcset_con_las_dos_medidas(self):
        p = self.crear_producto()
        srcset = miniaturas.srcset(p.imagen)
        self.assertIn('-400.webp 400w', srcset)
        self.assertIn('-800.webp 800w', srcset)

    def test_sin_miniaturas_srcset_vacio_y_url_original(self):
        p = self.crear_producto()
        for ancho in miniaturas.ANCHOS:
            default_storage.delete(miniaturas.nombre_miniatura(p.imagen.name, ancho))
        self.assertEqual(miniaturas.srcset(p.imagen), '')
        self.assertEqual(miniaturas.url(p.imagen), p.imagen.url)

    def test_comando_regenera_las_que_faltan(self):
        p = self.crear_producto()
        faltante = miniaturas.nombre_miniatura(p.imagen.name, 400)
        default_storage.delete(faltante)
        call_command('generar_miniaturas', stdout=io.StringIO())
        self.assertTrue(default_storage.exists(faltante))

    def test_tarjeta_del_catalogo_usa_srcset(self):
        p = self.crear_producto()
        StockTienda.objects.create(tienda=self.tienda, producto=p, cantidad=2)
        with self.settings(ECOMMERCE_TIENDA_ID=self.tienda.pk):
            resp = self.client.get(reverse('ecommerce:catalogo'))
        self.assertContains(resp, '-400.webp 400w')
        self.assertContains(resp, 'sizes="(max-width: 520px) 50vw')
