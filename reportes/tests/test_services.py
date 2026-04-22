"""Tests de las agregaciones de reportes.

Verificamos:
- ventas_por_canal cuenta solo recibos pagados y entrega ambos canales.
- ventas_por_periodo agrupa por día (TruncDate).
- top_productos rankea por unidades vendidas.
- resumen_negocio compone todas las piezas.
"""

from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from bodega.models import Tienda
from catalogo.models import Familia, Producto
from pos.models import ReciboVenta, ReciboVentaDetalle
from reportes.services import (
    resumen_negocio,
    top_productos,
    ventas_por_canal,
    ventas_por_periodo,
)


class ReportesSetup(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.familia = Familia.objects.create(nombre='Perfumes')
        cls.tienda = Tienda.objects.create(nombre_organizacion='T', activa=True)
        cls.producto_a = Producto.objects.create(
            familia=cls.familia, nombre='Perfume A',
            precio_base=Decimal('10000'), tiene_variantes=False,
        )
        cls.producto_b = Producto.objects.create(
            familia=cls.familia, nombre='Perfume B',
            precio_base=Decimal('20000'), tiene_variantes=False,
        )

    def _recibo(self, canal, estado, total, dias_atras=0, detalles=None):
        recibo = ReciboVenta.objects.create(
            canal=canal, tienda=self.tienda,
            subtotal=total, descuento=Decimal('0'), total=total,
            estado=estado,
        )
        if dias_atras:
            # auto_now_add → hay que hacer update.
            ReciboVenta.objects.filter(pk=recibo.pk).update(
                creado=timezone.now() - timedelta(days=dias_atras),
            )
            recibo.refresh_from_db()
        for det in detalles or []:
            ReciboVentaDetalle.objects.create(recibo=recibo, **det)
        return recibo


class VentasPorCanalTests(ReportesSetup):
    def test_cuenta_solo_pagados(self):
        self._recibo(ReciboVenta.CANAL_PRESENCIAL, ReciboVenta.ESTADO_PAGADO, Decimal('10000'))
        self._recibo(ReciboVenta.CANAL_PRESENCIAL, ReciboVenta.ESTADO_FALLIDO, Decimal('999'))
        self._recibo(ReciboVenta.CANAL_ONLINE, ReciboVenta.ESTADO_PAGADO, Decimal('20000'))

        data = ventas_por_canal()
        self.assertEqual(data['presencial']['n_ventas'], 1)
        self.assertEqual(data['presencial']['total'], Decimal('10000'))
        self.assertEqual(data['online']['n_ventas'], 1)
        self.assertEqual(data['online']['total'], Decimal('20000'))

    def test_incluye_ambos_canales_aunque_vacios(self):
        self._recibo(ReciboVenta.CANAL_PRESENCIAL, ReciboVenta.ESTADO_PAGADO, Decimal('10000'))
        data = ventas_por_canal()
        self.assertEqual(data['online']['n_ventas'], 0)
        self.assertEqual(data['online']['total'], Decimal('0'))


class VentasPorPeriodoTests(ReportesSetup):
    def test_agrupa_por_dia(self):
        self._recibo(ReciboVenta.CANAL_PRESENCIAL, ReciboVenta.ESTADO_PAGADO, Decimal('10000'))
        self._recibo(ReciboVenta.CANAL_PRESENCIAL, ReciboVenta.ESTADO_PAGADO, Decimal('5000'))
        self._recibo(
            ReciboVenta.CANAL_ONLINE, ReciboVenta.ESTADO_PAGADO,
            Decimal('7000'), dias_atras=2,
        )

        serie = ventas_por_periodo()
        self.assertEqual(len(serie), 2)
        # La serie viene ordenada ascendente por fecha.
        self.assertEqual(serie[0]['n_ventas'], 1)
        self.assertEqual(serie[0]['total'], Decimal('7000'))
        self.assertEqual(serie[1]['n_ventas'], 2)
        self.assertEqual(serie[1]['total'], Decimal('15000'))


class TopProductosTests(ReportesSetup):
    def test_ranking_por_unidades(self):
        self._recibo(
            ReciboVenta.CANAL_PRESENCIAL, ReciboVenta.ESTADO_PAGADO, Decimal('10000'),
            detalles=[{
                'producto': self.producto_a, 'descripcion': 'Perfume A',
                'cantidad': 3, 'precio_unitario': Decimal('10000'), 'descuento': Decimal('0'),
            }],
        )
        self._recibo(
            ReciboVenta.CANAL_ONLINE, ReciboVenta.ESTADO_PAGADO, Decimal('20000'),
            detalles=[{
                'producto': self.producto_b, 'descripcion': 'Perfume B',
                'cantidad': 1, 'precio_unitario': Decimal('20000'), 'descuento': Decimal('0'),
            }],
        )
        # Un recibo fallido no debería entrar al ranking.
        self._recibo(
            ReciboVenta.CANAL_PRESENCIAL, ReciboVenta.ESTADO_FALLIDO, Decimal('99000'),
            detalles=[{
                'producto': self.producto_a, 'descripcion': 'Perfume A',
                'cantidad': 50, 'precio_unitario': Decimal('10000'), 'descuento': Decimal('0'),
            }],
        )

        top = top_productos()
        self.assertEqual(len(top), 2)
        self.assertEqual(top[0]['descripcion'], 'Perfume A')
        self.assertEqual(top[0]['unidades'], 3)
        self.assertEqual(top[0]['ingreso'], Decimal('30000'))
        self.assertEqual(top[1]['descripcion'], 'Perfume B')
        self.assertEqual(top[1]['unidades'], 1)


class ResumenNegocioTests(ReportesSetup):
    def test_compone_todo(self):
        self._recibo(ReciboVenta.CANAL_PRESENCIAL, ReciboVenta.ESTADO_PAGADO, Decimal('10000'))

        resumen = resumen_negocio()
        self.assertEqual(resumen.total_ventas, Decimal('10000'))
        self.assertEqual(resumen.n_ventas, 1)
        self.assertIn('presencial', resumen.ventas_por_canal)
        self.assertIn('online', resumen.ventas_por_canal)
        self.assertIsNotNone(resumen.caja)
        self.assertIsNotNone(resumen.valor_inventario)
