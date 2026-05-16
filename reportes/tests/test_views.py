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
        # BUG-005: el monto va formateado en CLP (con separador de miles).
        self.assertContains(resp, '$10.000')  # total de ventas / promedio
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


class ProduccionViewTests(TestCase):
    """Smoke de /reportes/produccion/ (Fase K)."""

    @classmethod
    def setUpTestData(cls):
        from bodega.models import Bodega, Material, Rendimiento, StockMaterial
        from catalogo.models import Familia, Producto, ProductoVariante

        cls.admin = User.objects.create_superuser('an', 'a@a.cl', 'x')
        cls.tienda = Tienda.objects.create(nombre_organizacion='LV', activa=True)
        cls.bodega = Bodega.objects.create(tienda=cls.tienda, nombre='B-LV')
        material = Material.objects.create(
            nombre='Tela buzo', costo_unitario_referencia=Decimal('40000'),
        )
        fam = Familia.objects.create(nombre='Uniformes')
        prod = Producto.objects.create(
            familia=fam, nombre='Buzo SFJ',
            precio_base=Decimal('30000'), tiene_variantes=True,
        )
        var = ProductoVariante.objects.create(producto=prod, sku='BZ-M')
        Rendimiento.objects.create(material=material, variante=var, unidades_por_rollo=50)
        StockMaterial.objects.create(bodega=cls.bodega, material=material, cantidad=4)

    def test_admin_ve_capacidad(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse('reportes:produccion'))
        self.assertEqual(resp.status_code, 200)
        # 4 rollos × 50 u/rollo = 200 unidades
        self.assertContains(resp, '200')
        # Valor potencial = 200 × $30.000 = $6.000.000 → '6.000.000' con intcomma
        self.assertContains(resp, '6.000.000')
        # Costo materiales = 4 × $40.000 = $160.000
        self.assertContains(resp, '160.000')

    def test_no_admin_rebota(self):
        User.objects.create_user('cli', password='x')
        self.client.login(username='cli', password='x')
        resp = self.client.get(reverse('reportes:produccion'))
        self.assertEqual(resp.status_code, 302)
