"""Bloque 9: Reseñas reales — modelo, form/view de envio, render en PDP."""
from decimal import Decimal

from django.test import TestCase, override_settings
from django.urls import reverse

from bodega.models import StockTienda, Tienda
from catalogo.models import Familia, Producto, Resena


@override_settings(ECOMMERCE_PAYMENT_GATEWAY='mock')
class ResenaModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.fam = Familia.objects.create(nombre='Perfumes')
        cls.producto = Producto.objects.create(
            familia=cls.fam, nombre='Perfume Test',
            precio_base=Decimal('20000'), tiene_variantes=False,
        )

    def _crear_resena(self, **kwargs):
        defaults = {
            'producto': self.producto,
            'estrellas': 5,
            'titulo': 'Excelente',
            'texto': 'Me encanto el aroma, muy duradero.',
            'nombre_publico': 'Maria',
            'cliente_email': 'maria@example.com',
            'estado': Resena.ESTADO_APROBADA,
        }
        defaults.update(kwargs)
        return Resena.objects.create(**defaults)

    def test_promedio_y_count_solo_resenas_aprobadas(self):
        self._crear_resena(estrellas=5)
        self._crear_resena(estrellas=3)
        # Una pendiente NO debe contar.
        self._crear_resena(estrellas=1, estado=Resena.ESTADO_PENDIENTE)
        # Una rechazada tampoco.
        self._crear_resena(estrellas=1, estado=Resena.ESTADO_RECHAZADA)

        producto = Producto.objects.get(pk=self.producto.pk)
        self.assertEqual(producto.resena_count, 2)
        self.assertEqual(producto.resena_promedio, 4.0)
        self.assertEqual(producto.resena_promedio_redondo, 4)

    def test_sin_resenas_aprobadas_promedio_es_none(self):
        self._crear_resena(estrellas=5, estado=Resena.ESTADO_PENDIENTE)
        producto = Producto.objects.get(pk=self.producto.pk)
        self.assertEqual(producto.resena_count, 0)
        self.assertIsNone(producto.resena_promedio)
        self.assertEqual(producto.resena_promedio_redondo, 0)


@override_settings(ECOMMERCE_PAYMENT_GATEWAY='mock')
class EnviarResenaViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tienda = Tienda.objects.create(nombre_organizacion='Online', activa=True)
        cls.fam = Familia.objects.create(nombre='Perfumes')
        cls.producto = Producto.objects.create(
            familia=cls.fam, nombre='Yara EDP',
            precio_base=Decimal('20000'), tiene_variantes=False,
        )
        StockTienda.objects.create(tienda=cls.tienda, producto=cls.producto, cantidad=2)

    def setUp(self):
        self.url = reverse('ecommerce:enviar_resena', args=[self.producto.pk])
        self.settings_override = self.settings(ECOMMERCE_TIENDA_ID=self.tienda.pk)
        self.settings_override.enable()

    def tearDown(self):
        self.settings_override.disable()

    def _post(self, **overrides):
        data = {
            'producto_id': self.producto.pk,
            'estrellas': 5,
            'titulo': 'Increible',
            'texto': 'Muy buena calidad y atencion.',
            'nombre_publico': 'Cliente Test',
            'cliente_email': 'cliente@example.com',
        }
        data.update(overrides)
        return self.client.post(self.url, data)

    def test_envio_valido_crea_resena_pendiente(self):
        r = self._post()
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Resena.objects.count(), 1)
        resena = Resena.objects.get()
        self.assertEqual(resena.estrellas, 5)
        self.assertEqual(resena.estado, Resena.ESTADO_PENDIENTE)
        self.assertEqual(resena.cliente_email, 'cliente@example.com')

    def test_envio_valido_htmx_devuelve_partial_done(self):
        r = self._post(**{'HTTP_HX_REQUEST': 'true'}) if False else self.client.post(
            self.url,
            {
                'producto_id': self.producto.pk,
                'estrellas': 5,
                'titulo': 'OK',
                'texto': 'Producto correcto.',
                'nombre_publico': 'X',
                'cliente_email': 'x@example.com',
            },
            HTTP_HX_REQUEST='true',
        )
        self.assertEqual(r.status_code, 200)
        self.assertIn(b'Gracias por tu opini', r.content)

    def test_estrellas_fuera_de_rango_no_crea_resena(self):
        r = self._post(estrellas=7)
        # No-HTMX: redirect con messages.error.
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Resena.objects.count(), 0)

    def test_texto_muy_corto_no_crea_resena(self):
        r = self._post(texto='no')
        self.assertEqual(Resena.objects.count(), 0)

    def test_email_invalido_no_crea_resena(self):
        r = self._post(cliente_email='not-an-email')
        self.assertEqual(Resena.objects.count(), 0)

    def test_producto_id_distinto_al_de_url_rechaza(self):
        otro = Producto.objects.create(
            familia=self.fam, nombre='Otro', precio_base=Decimal('1000'),
        )
        r = self._post(producto_id=otro.pk)
        self.assertEqual(Resena.objects.count(), 0)

    def test_pdp_muestra_resenas_aprobadas_y_oculta_pendientes(self):
        Resena.objects.create(
            producto=self.producto, estrellas=5, texto='Aprobada visible',
            nombre_publico='Ana', cliente_email='ana@example.com',
            estado=Resena.ESTADO_APROBADA,
        )
        Resena.objects.create(
            producto=self.producto, estrellas=1, texto='Pendiente oculta',
            nombre_publico='Spam', cliente_email='spam@example.com',
            estado=Resena.ESTADO_PENDIENTE,
        )
        r = self.client.get(reverse('ecommerce:producto', args=[self.producto.pk]))
        self.assertContains(r, 'Aprobada visible')
        self.assertNotContains(r, 'Pendiente oculta')
        # Promedio 5.0 con una sola aprobada.
        self.assertContains(r, '5.0')

    def test_pdp_sin_resenas_invita_a_ser_el_primero(self):
        r = self.client.get(reverse('ecommerce:producto', args=[self.producto.pk]))
        self.assertContains(r, 'Sé el primero en opinar')

    def test_pdp_incluye_form_de_resena_con_csrf(self):
        r = self.client.get(reverse('ecommerce:producto', args=[self.producto.pk]))
        self.assertContains(r, 'name="estrellas"')
        self.assertContains(r, 'csrfmiddlewaretoken')
