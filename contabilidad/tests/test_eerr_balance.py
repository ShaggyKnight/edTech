"""Tests de Estado de Resultados + Balance General — Fase O."""
from datetime import datetime, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from bodega.models import Bodega, Material, StockMaterial, StockTienda, Tienda
from catalogo.models import Familia, Producto
from contabilidad.models import MovimientoCaja
from contabilidad.services import (
    balance_general,
    estado_resultados,
    registrar_ingreso_venta,
    registrar_salida,
    serie_mensual,
)
from pos.models import ReciboVenta, ReciboVentaDetalle

User = get_user_model()


class EstadoResultadosTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tienda = Tienda.objects.create(nombre_organizacion='LV', activa=True)
        cls.fam = Familia.objects.create(nombre='Perfumes')
        cls.producto = Producto.objects.create(
            familia=cls.fam, nombre='Perfume',
            precio_base=Decimal('15000'), precio_costo=Decimal('5000'),
            tiene_variantes=False,
        )

    def _crear_venta(self, total, cantidad):
        recibo = ReciboVenta.objects.create(
            canal=ReciboVenta.CANAL_PRESENCIAL, tienda=self.tienda,
            subtotal=total, total=total, estado=ReciboVenta.ESTADO_PAGADO,
        )
        ReciboVentaDetalle.objects.create(
            recibo=recibo, producto=self.producto, cantidad=cantidad,
            precio_unitario=total / cantidad, descripcion='Perfume',
        )
        registrar_ingreso_venta(recibo)
        return recibo

    def test_eerr_simple(self):
        """Vendo 2 perfumes a $15.000 cada uno: ingresos $30k, COGS $10k,
        margen $20k, sin gastos → utilidad $20k."""
        self._crear_venta(Decimal('30000'), 2)
        ahora = timezone.now()
        eerr = estado_resultados(
            desde=ahora - timedelta(days=1),
            hasta=ahora + timedelta(days=1),
            tienda=self.tienda,
        )
        self.assertEqual(eerr.ingresos, Decimal('30000'))
        self.assertEqual(eerr.costo_ventas, Decimal('10000'))
        self.assertEqual(eerr.margen_bruto, Decimal('20000'))
        self.assertEqual(eerr.gastos_operativos, Decimal('0'))
        self.assertEqual(eerr.utilidad_neta, Decimal('20000'))

    def test_gasto_operativo_resta_utilidad(self):
        self._crear_venta(Decimal('30000'), 2)
        registrar_salida(
            tienda=self.tienda, monto=Decimal('5000'),
            concepto='Arriendo',  # default categoria=GASTO_OPERATIVO
        )
        ahora = timezone.now()
        eerr = estado_resultados(
            desde=ahora - timedelta(days=1),
            hasta=ahora + timedelta(days=1),
            tienda=self.tienda,
        )
        self.assertEqual(eerr.gastos_operativos, Decimal('5000'))
        self.assertEqual(eerr.utilidad_neta, Decimal('15000'))  # 20k − 5k

    def test_costo_inventario_no_aparece_en_eerr(self):
        """Compras de tela / pagos de confección no afectan utilidad —
        son flujos de caja, no gastos."""
        self._crear_venta(Decimal('30000'), 2)
        registrar_salida(
            tienda=self.tienda, monto=Decimal('100000'),
            concepto='Compra material: tela X',
            categoria=MovimientoCaja.COSTO_INVENTARIO,
        )
        registrar_salida(
            tienda=self.tienda, monto=Decimal('50000'),
            concepto='Confección lote: 100',
            categoria=MovimientoCaja.COSTO_PRODUCCION,
        )
        ahora = timezone.now()
        eerr = estado_resultados(
            desde=ahora - timedelta(days=1),
            hasta=ahora + timedelta(days=1),
            tienda=self.tienda,
        )
        # Solo la utilidad por la venta — los costos de inventario están
        # "guardados" en stock, aparecen en EERR cuando se vendan.
        self.assertEqual(eerr.gastos_operativos, Decimal('0'))
        self.assertEqual(eerr.utilidad_neta, Decimal('20000'))


class BalanceGeneralTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tienda = Tienda.objects.create(nombre_organizacion='LV', activa=True)
        cls.bodega = Bodega.objects.create(tienda=cls.tienda, nombre='B')
        cls.fam = Familia.objects.create(nombre='Perfumes')
        cls.producto = Producto.objects.create(
            familia=cls.fam, nombre='Perfume',
            precio_base=Decimal('15000'), precio_costo=Decimal('5000'),
            tiene_variantes=False,
        )
        cls.material = Material.objects.create(
            nombre='Tela', costo_unitario_referencia=Decimal('40000'),
        )

    def test_balance_simple(self):
        # Stock terminado: 4 perfumes a $5000 costo = $20.000.
        StockTienda.objects.create(tienda=self.tienda, producto=self.producto, cantidad=4)
        # Materia prima: 3 rollos a $40.000 = $120.000.
        StockMaterial.objects.create(bodega=self.bodega, material=self.material, cantidad=3)
        # Caja: ingreso de $50.000 - salida de $10.000 = $40.000.
        registrar_salida(tienda=self.tienda, monto=Decimal('10000'), concepto='X')
        # Faking entrada manual:
        MovimientoCaja.objects.create(
            tienda=self.tienda, tipo=MovimientoCaja.ENTRADA,
            categoria=MovimientoCaja.OTRO, monto=Decimal('50000'),
            concepto='aporte capital',
        )

        bal = balance_general(tienda=self.tienda)
        self.assertEqual(bal.caja, Decimal('40000'))
        self.assertEqual(bal.inventario_terminado, Decimal('20000'))
        self.assertEqual(bal.inventario_materia_prima, Decimal('120000'))
        self.assertEqual(bal.total_activos, Decimal('180000'))
        self.assertEqual(bal.total_pasivos, Decimal('0'))
        self.assertEqual(bal.patrimonio, Decimal('180000'))

    def test_caja_negativa_si_salidas_superan_entradas(self):
        registrar_salida(tienda=self.tienda, monto=Decimal('30000'), concepto='X')
        bal = balance_general(tienda=self.tienda)
        self.assertEqual(bal.caja, Decimal('-30000'))


class SerieMensualTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tienda = Tienda.objects.create(nombre_organizacion='LV', activa=True)

    def test_genera_meses_consecutivos(self):
        desde = timezone.make_aware(datetime(2026, 1, 1))
        hasta = timezone.make_aware(datetime(2026, 4, 30))
        serie = serie_mensual(desde=desde, hasta=hasta, tienda=self.tienda)
        self.assertEqual(len(serie), 4)
        self.assertEqual([p.mes for p in serie], [1, 2, 3, 4])
        self.assertEqual([p.anio for p in serie], [2026] * 4)
        self.assertIn('Ene 2026', serie[0].label)
        self.assertIn('Abr 2026', serie[3].label)


class ViewsEerrBalanceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser('root', 'r@x.cl', 'x')
        cls.tienda = Tienda.objects.create(nombre_organizacion='LV', activa=True)

    def test_eerr_view_admin_ve(self):
        self.client.force_login(self.admin)
        from django.urls import reverse
        resp = self.client.get(reverse('reportes:eerr'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Estado de Resultados')

    def test_balance_view_admin_ve(self):
        self.client.force_login(self.admin)
        from django.urls import reverse
        resp = self.client.get(reverse('reportes:balance'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Balance General')

    def test_no_admin_rebota(self):
        cli = User.objects.create_user('cli', password='x')
        self.client.force_login(cli)
        from django.urls import reverse
        for name in ('reportes:eerr', 'reportes:balance'):
            resp = self.client.get(reverse(name))
            self.assertEqual(resp.status_code, 302)
