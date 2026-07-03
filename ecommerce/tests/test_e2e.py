"""Smoke test end-to-end del flujo de compra online con el cliente de Django."""

from decimal import Decimal

from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from bodega.models import StockTienda, Tienda
from catalogo.models import Familia, Producto
from pos.models import ReciboVenta


@override_settings(
    ECOMMERCE_PAYMENT_GATEWAY='mock',
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
)
class EcommerceFlujoCompletoTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.familia = Familia.objects.create(nombre='Perfumes')
        cls.tienda = Tienda.objects.create(nombre_organizacion='Tienda Online', activa=True)
        cls.producto = Producto.objects.create(
            familia=cls.familia,
            nombre='Perfume 30ml',
            precio_base=Decimal('12000'),
            tiene_variantes=False,
        )
        StockTienda.objects.create(tienda=cls.tienda, producto=cls.producto, cantidad=10)

    def test_flujo_catalogo_carrito_checkout_pago_boleta(self):
        with self.settings(ECOMMERCE_TIENDA_ID=self.tienda.pk):
            # Catálogo muestra el producto con stock.
            resp = self.client.get(reverse('ecommerce:catalogo'))
            self.assertEqual(resp.status_code, 200)
            self.assertContains(resp, 'Perfume 30ml')

            # Detalle del producto.
            resp = self.client.get(reverse('ecommerce:producto', args=[self.producto.pk]))
            self.assertEqual(resp.status_code, 200)
            self.assertContains(resp, 'Agregar al carrito')

            # Agregar al carrito.
            resp = self.client.post(reverse('ecommerce:agregar'), {
                'tipo': 'p',
                'item_id': self.producto.pk,
                'cantidad': 2,
            }, follow=True)
            self.assertEqual(resp.status_code, 200)
            # El nuevo diseño usa "Total" (title-case) en el resumen del carrito.
            self.assertContains(resp, 'Total')

            # Ir al checkout.
            resp = self.client.get(reverse('ecommerce:checkout'))
            self.assertEqual(resp.status_code, 200)

            # Iniciar pago: redirige al mock de pasarela.
            resp = self.client.post(reverse('ecommerce:checkout_iniciar'), {
                'cliente_nombre': 'Juana Pérez',
                'cliente_email': 'juana@example.cl',
                'cliente_telefono': '+56 9 5544 3322',
            })
            self.assertEqual(resp.status_code, 302)
            self.assertIn('mock-pago', resp['Location'])

            # Extraer el token y return_url de la URL de la pasarela.
            from urllib.parse import parse_qs, urlparse
            parsed = urlparse(resp['Location'])
            params = parse_qs(parsed.query)
            token = params['token'][0]
            return_url = params['return_url'][0]

            # Usuario aprueba en la pasarela simulada.
            resp = self.client.post(
                reverse('ecommerce:mock_pago') + f'?token={token}&return_url={return_url}',
                {'decision': 'aprobar'},
            )
            self.assertEqual(resp.status_code, 302)
            self.assertIn('token_ws=', resp['Location'])

            # Volver al sitio desde la pasarela → checkout_retorno.
            resp = self.client.get(resp['Location'], follow=True)
            self.assertEqual(resp.status_code, 200)

            # Recibo creado, pagado, stock descontado.
            recibo = ReciboVenta.objects.get()
            self.assertEqual(recibo.estado, ReciboVenta.ESTADO_PAGADO)
            self.assertEqual(recibo.canal, ReciboVenta.CANAL_ONLINE)
            self.assertEqual(recibo.total, Decimal('24000'))
            self.assertEqual(recibo.cliente_nombre, 'Juana Pérez')

            stock = StockTienda.objects.get(tienda=self.tienda, producto=self.producto)
            self.assertEqual(stock.cantidad, 8)

            # Boleta enviada por email.
            self.assertEqual(len(mail.outbox), 1)
            self.assertIn('juana@example.cl', mail.outbox[0].to)
            self.assertIn(f'#{recibo.pk}', mail.outbox[0].subject)

    def test_flujo_rechazo_no_descuenta_stock(self):
        with self.settings(ECOMMERCE_TIENDA_ID=self.tienda.pk):
            self.client.post(reverse('ecommerce:agregar'), {
                'tipo': 'p', 'item_id': self.producto.pk, 'cantidad': 1,
            })
            resp = self.client.post(reverse('ecommerce:checkout_iniciar'), {
                'cliente_nombre': 'X', 'cliente_email': 'x@x.cl',
                'cliente_telefono': '955443322',
            })
            from urllib.parse import parse_qs, urlparse
            params = parse_qs(urlparse(resp['Location']).query)
            token = params['token'][0]
            return_url = params['return_url'][0]

            # Rechazo en la pasarela.
            resp = self.client.post(
                reverse('ecommerce:mock_pago') + f'?token={token}&return_url={return_url}',
                {'decision': 'rechazar'},
            )
            resp = self.client.get(resp['Location'])
            self.assertEqual(resp.status_code, 200)
            self.assertContains(resp, 'Pago rechazado')

            recibo = ReciboVenta.objects.get()
            self.assertEqual(recibo.estado, ReciboVenta.ESTADO_FALLIDO)

            stock = StockTienda.objects.get(tienda=self.tienda, producto=self.producto)
            self.assertEqual(stock.cantidad, 10)

    def test_catalogo_sin_tienda_configurada_retorna_503(self):
        with self.settings(ECOMMERCE_TIENDA_ID=None):
            resp = self.client.get(reverse('ecommerce:catalogo'))
            self.assertEqual(resp.status_code, 503)
            self.assertContains(resp, 'mantención', status_code=503)
