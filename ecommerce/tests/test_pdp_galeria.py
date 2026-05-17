"""Bloque 8: Galeria real PDP — tests del modelo + render del PDP."""
from decimal import Decimal
from io import BytesIO

from django.core.files.base import ContentFile
from django.test import TestCase, override_settings
from django.urls import reverse

from bodega.models import StockTienda, Tienda
from catalogo.models import Familia, Producto, ProductoImagen


def _imagen_dummy(name='dummy.jpg'):
    """Devuelve un ContentFile con bytes minimos validos de JPG para
    pasar la validacion de ImageField sin Pillow real (tests usan
    in-memory storage). Bytes magicos de JPG `\\xff\\xd8\\xff\\xe0`."""
    return ContentFile(b'\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00', name=name)


@override_settings(ECOMMERCE_PAYMENT_GATEWAY='mock')
class GaleriaModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.fam = Familia.objects.create(nombre='Perfumes')
        cls.producto = Producto.objects.create(
            familia=cls.fam, nombre='Perfume Test',
            precio_base=Decimal('20000'), tiene_variantes=False,
        )

    def test_orden_default_asc(self):
        # Tres imagenes con orden mezclado — deben salir 0,1,5
        img_c = ProductoImagen.objects.create(producto=self.producto, orden=5)
        img_a = ProductoImagen.objects.create(producto=self.producto, orden=0)
        img_b = ProductoImagen.objects.create(producto=self.producto, orden=1)
        imgs = list(self.producto.imagenes.all())
        self.assertEqual([img_a.pk, img_b.pk, img_c.pk], [i.pk for i in imgs])

    def test_alt_fallback_al_str(self):
        img = ProductoImagen.objects.create(producto=self.producto, alt='Vista trasera')
        self.assertEqual(img.alt, 'Vista trasera')

    def test_str_incluye_producto(self):
        img = ProductoImagen.objects.create(producto=self.producto)
        self.assertIn(self.producto.nombre, str(img))


@override_settings(ECOMMERCE_PAYMENT_GATEWAY='mock')
class GaleriaPDPTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tienda = Tienda.objects.create(nombre_organizacion='Online', activa=True)
        cls.fam = Familia.objects.create(nombre='Perfumes')
        cls.producto = Producto.objects.create(
            familia=cls.fam, nombre='Yara EDP',
            precio_base=Decimal('25000'), tiene_variantes=False,
        )
        StockTienda.objects.create(tienda=cls.tienda, producto=cls.producto, cantidad=2)

    def setUp(self):
        self.settings_override = self.settings(ECOMMERCE_TIENDA_ID=self.tienda.pk)
        self.settings_override.enable()

    def tearDown(self):
        self.settings_override.disable()

    def test_sin_imagenes_galeria_data_has_extra_es_0(self):
        url = reverse('ecommerce:producto', args=[self.producto.pk])
        r = self.client.get(url)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'data-has-extra="0"')

    def test_con_imagenes_galeria_data_has_extra_es_1(self):
        ProductoImagen.objects.create(
            producto=self.producto, imagen=_imagen_dummy('a.jpg'),
            orden=0, alt='Lateral',
        )
        ProductoImagen.objects.create(
            producto=self.producto, imagen=_imagen_dummy('b.jpg'),
            orden=1, alt='Frasco',
        )
        url = reverse('ecommerce:producto', args=[self.producto.pk])
        r = self.client.get(url)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'data-has-extra="1"')
        # Las dos imagenes adicionales aparecen como botones con alt.
        self.assertContains(r, 'alt="Lateral"')
        self.assertContains(r, 'alt="Frasco"')

    def test_orden_de_los_thumbs_respeta_orden(self):
        # orden 5 va al final, orden 0 al principio.
        ProductoImagen.objects.create(
            producto=self.producto, imagen=_imagen_dummy('z.jpg'),
            orden=5, alt='Z-alt',
        )
        ProductoImagen.objects.create(
            producto=self.producto, imagen=_imagen_dummy('a.jpg'),
            orden=0, alt='A-alt',
        )
        url = reverse('ecommerce:producto', args=[self.producto.pk])
        r = self.client.get(url)
        body = r.content.decode('utf-8')
        # A-alt debe aparecer antes que Z-alt en el HTML.
        idx_a = body.find('A-alt')
        idx_z = body.find('Z-alt')
        self.assertGreater(idx_a, 0)
        self.assertGreater(idx_z, 0)
        self.assertLess(idx_a, idx_z)

    def test_alt_fallback_a_nombre_producto_si_vacio(self):
        ProductoImagen.objects.create(
            producto=self.producto, imagen=_imagen_dummy('nialt.jpg'),
            orden=0, alt='',
        )
        url = reverse('ecommerce:producto', args=[self.producto.pk])
        r = self.client.get(url)
        # alt='' usa default:producto.nombre → "Yara EDP"
        self.assertContains(r, 'alt="Yara EDP"')
