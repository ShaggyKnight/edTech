"""Smoke tests de las vistas de reportes.

- Un usuario no admin es rebotado.
- Un superuser ve el dashboard con los números correctos.
- La vista de caja permite registrar una salida.
"""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from bodega.models import Tienda
from contabilidad.models import MovimientoCaja
from contabilidad.services import registrar_ingreso_venta
from pos.models import ReciboVenta

User = get_user_model()


class DashboardAccesoTests(TestCase):
    def test_anonimo_redirige_a_login(self):
        resp = self.client.get(reverse('reportes:dashboard'))
        self.assertEqual(resp.status_code, 302)

    def test_usuario_sin_rol_recibe_redirect_o_forbidden(self):
        User.objects.create_user('juan', password='x')
        self.client.login(username='juan', password='x')
        resp = self.client.get(reverse('reportes:dashboard'))
        # user_passes_test sin rol admin redirige al login.
        self.assertEqual(resp.status_code, 302)


class DashboardContenidoTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser('ana', 'a@a.cl', 'x')
        cls.tienda = Tienda.objects.create(nombre_organizacion='Central', activa=True)
        # Una venta pagada presencial → debe aparecer + asiento de caja.
        recibo = ReciboVenta.objects.create(
            canal=ReciboVenta.CANAL_PRESENCIAL,
            tienda=cls.tienda,
            subtotal=Decimal('10000'), descuento=Decimal('0'), total=Decimal('10000'),
            estado=ReciboVenta.ESTADO_PAGADO,
        )
        registrar_ingreso_venta(recibo)

    def test_admin_ve_dashboard_con_totales(self):
        self.client.login(username='ana', password='x')
        resp = self.client.get(reverse('reportes:dashboard'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Dashboard')
        self.assertContains(resp, '$10000')  # total de ventas
        self.assertContains(resp, 'Central')  # tienda en el selector


class CajaViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser('ana', 'a@a.cl', 'x')
        cls.tienda = Tienda.objects.create(nombre_organizacion='Central', activa=True)

    def test_registrar_salida_manual(self):
        self.client.login(username='ana', password='x')
        resp = self.client.post(reverse('reportes:caja'), {
            'tienda': self.tienda.pk,
            'monto': '50000',
            'concepto': 'Arriendo abril',
        }, follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(MovimientoCaja.objects.filter(
            tipo=MovimientoCaja.SALIDA, monto=Decimal('50000'),
            concepto='Arriendo abril',
        ).exists())
