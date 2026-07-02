"""Bloque 9: Reseñas reales — modelo, form/view de envio, render en PDP."""
from decimal import Decimal

from django.test import TestCase, override_settings
from django.urls import reverse

from bodega.models import StockTienda, Tienda
from catalogo.models import Familia, Producto, Resena


@override_settings(ECOMMERCE_PAYMENT_GATEWAY='mock', FEATURE_RESENAS=True)
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


@override_settings(ECOMMERCE_PAYMENT_GATEWAY='mock', FEATURE_RESENAS=True)
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
        # Promedio 5.0 con una sola aprobada. floatformat localiza el
        # decimal (es-CL renderiza "5,0") — aceptar coma o punto.
        self.assertRegex(r.content.decode(), r'5[.,]0')

    def test_pdp_sin_resenas_invita_a_ser_el_primero(self):
        r = self.client.get(reverse('ecommerce:producto', args=[self.producto.pk]))
        self.assertContains(r, 'Sé el primero en opinar')

    def test_pdp_incluye_form_de_resena_con_csrf(self):
        r = self.client.get(reverse('ecommerce:producto', args=[self.producto.pk]))
        self.assertContains(r, 'name="estrellas"')
        self.assertContains(r, 'csrfmiddlewaretoken')


@override_settings(ECOMMERCE_PAYMENT_GATEWAY='mock', FEATURE_RESENAS=False)
class FeatureFlagResenasOffTests(TestCase):
    """Cuando FEATURE_RESENAS=False (default), la UI esta oculta y el
    endpoint de envio devuelve 404. Asi mantenemos el modelo + admin
    + tests por si la duena la prende mas adelante, sin exponer la
    feature publicamente."""

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
        self.so = self.settings(ECOMMERCE_TIENDA_ID=self.tienda.pk)
        self.so.enable()

    def tearDown(self):
        self.so.disable()

    def test_pdp_no_muestra_seccion_de_resenas(self):
        # Aun si hay una resena aprobada, no debe renderizarse en el PDP.
        Resena.objects.create(
            producto=self.producto, estrellas=5, texto='Excelente producto',
            nombre_publico='Ana', cliente_email='ana@example.com',
            estado=Resena.ESTADO_APROBADA,
        )
        r = self.client.get(reverse('ecommerce:producto', args=[self.producto.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, '<h2>Reseñas</h2>')
        self.assertNotContains(r, 'Excelente producto')
        # Tambien debe estar oculto el rating del header.
        self.assertNotContains(r, 'class="pdp-rating"')

    def test_endpoint_enviar_resena_devuelve_404(self):
        """Aun con datos validos, el POST debe ser 404 cuando la
        feature esta apagada — evita que alguien postee scrapeando la URL."""
        r = self.client.post(
            reverse('ecommerce:enviar_resena', args=[self.producto.pk]),
            {
                'producto_id': self.producto.pk,
                'estrellas': 5,
                'titulo': 'OK',
                'texto': 'Quiero opinar antes de tiempo.',
                'nombre_publico': 'Hacker',
                'cliente_email': 'h@example.com',
            },
        )
        self.assertEqual(r.status_code, 404)
        self.assertEqual(Resena.objects.count(), 0)
