"""Tests de los servicios contables.

Cubrimos:
- registrar_ingreso_venta es idempotente (un recibo → a lo más un asiento).
- registrar_ingreso_venta ignora recibos no pagados.
- registrar_salida valida monto > 0 y concepto no vacío.
- resumen_caja aplica filtros y calcula saldo.
- valor_inventario suma stock × precio_costo por variante y producto directo.
"""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from bodega.models import StockTienda, Tienda
from catalogo.models import (
    Atributo,
    Familia,
    Producto,
    ProductoVariante,
    ValorAtributo,
)
from contabilidad.models import MovimientoCaja
from contabilidad.services import (
    registrar_ingreso_venta,
    registrar_salida,
    resumen_caja,
    valor_inventario,
)
from pos.models import ReciboVenta

User = get_user_model()


class RegistrarIngresoVentaTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tienda = Tienda.objects.create(nombre_organizacion='T', activa=True)

    def _recibo(self, estado=ReciboVenta.ESTADO_PAGADO, total=Decimal('15000')):
        return ReciboVenta.objects.create(
            canal=ReciboVenta.CANAL_PRESENCIAL,
            tienda=self.tienda,
            subtotal=total, descuento=Decimal('0'), total=total,
            estado=estado,
        )

    def test_crea_entrada_por_recibo_pagado(self):
        recibo = self._recibo()
        mov = registrar_ingreso_venta(recibo)
        self.assertIsNotNone(mov)
        self.assertEqual(mov.tipo, MovimientoCaja.ENTRADA)
        self.assertEqual(mov.monto, Decimal('15000'))
        self.assertEqual(mov.recibo_venta, recibo)
        self.assertEqual(mov.tienda, self.tienda)
        self.assertIn(f'#{recibo.pk}', mov.concepto)

    def test_idempotente_en_llamadas_repetidas(self):
        recibo = self._recibo()
        registrar_ingreso_venta(recibo)
        segundo = registrar_ingreso_venta(recibo)
        self.assertIsNone(segundo)
        self.assertEqual(
            MovimientoCaja.objects.filter(recibo_venta=recibo).count(), 1
        )

    def test_ignora_recibo_no_pagado(self):
        recibo = self._recibo(estado=ReciboVenta.ESTADO_PENDIENTE)
        self.assertIsNone(registrar_ingreso_venta(recibo))
        self.assertFalse(MovimientoCaja.objects.exists())


class RegistrarSalidaTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tienda = Tienda.objects.create(nombre_organizacion='T', activa=True)

    def test_crea_salida(self):
        mov = registrar_salida(
            tienda=self.tienda, monto=Decimal('50000'), concepto='Arriendo abril',
        )
        self.assertEqual(mov.tipo, MovimientoCaja.SALIDA)
        self.assertEqual(mov.monto, Decimal('50000'))
        self.assertEqual(mov.concepto, 'Arriendo abril')

    def test_monto_no_positivo_falla(self):
        with self.assertRaises(ValueError):
            registrar_salida(tienda=self.tienda, monto=Decimal('0'), concepto='x')
        with self.assertRaises(ValueError):
            registrar_salida(tienda=self.tienda, monto=Decimal('-10'), concepto='x')

    def test_concepto_vacio_falla(self):
        with self.assertRaises(ValueError):
            registrar_salida(tienda=self.tienda, monto=Decimal('1'), concepto='   ')


class ResumenCajaTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tienda_a = Tienda.objects.create(nombre_organizacion='A', activa=True)
        cls.tienda_b = Tienda.objects.create(nombre_organizacion='B', activa=True)
        # Sembramos movimientos.
        MovimientoCaja.objects.create(
            tienda=cls.tienda_a, tipo=MovimientoCaja.ENTRADA,
            monto=Decimal('10000'), concepto='venta',
        )
        MovimientoCaja.objects.create(
            tienda=cls.tienda_a, tipo=MovimientoCaja.SALIDA,
            monto=Decimal('3000'), concepto='x',
        )
        MovimientoCaja.objects.create(
            tienda=cls.tienda_b, tipo=MovimientoCaja.ENTRADA,
            monto=Decimal('5000'), concepto='venta',
        )

    def test_global(self):
        r = resumen_caja()
        self.assertEqual(r.entradas, Decimal('15000'))
        self.assertEqual(r.salidas, Decimal('3000'))
        self.assertEqual(r.saldo, Decimal('12000'))

    def test_filtrado_por_tienda(self):
        r = resumen_caja(tienda=self.tienda_a)
        self.assertEqual(r.entradas, Decimal('10000'))
        self.assertEqual(r.salidas, Decimal('3000'))

        r = resumen_caja(tienda=self.tienda_b)
        self.assertEqual(r.entradas, Decimal('5000'))
        self.assertEqual(r.salidas, Decimal('0'))


class ValorInventarioTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.familia = Familia.objects.create(nombre='Perfumes')
        cls.tienda = Tienda.objects.create(nombre_organizacion='T', activa=True)

        cls.producto_directo = Producto.objects.create(
            familia=cls.familia, nombre='Difusor',
            precio_base=Decimal('12000'), precio_costo=Decimal('5000'),
            tiene_variantes=False,
        )
        cls.producto_con_variantes = Producto.objects.create(
            familia=cls.familia, nombre='Camisa',
            precio_base=Decimal('20000'), precio_costo=Decimal('8000'),
            tiene_variantes=True,
        )
        talla = Atributo.objects.create(nombre='Talla')
        valor = ValorAtributo.objects.create(atributo=talla, valor='M')
        cls.variante = ProductoVariante.objects.create(
            producto=cls.producto_con_variantes, sku='CAM-M',
        )
        cls.variante.valores.add(valor)

        StockTienda.objects.create(
            tienda=cls.tienda, producto=cls.producto_directo, cantidad=4,
        )
        StockTienda.objects.create(
            tienda=cls.tienda, variante=cls.variante, cantidad=3,
        )

    def test_suma_directos_y_variantes(self):
        # 4 × 5000 + 3 × 8000 = 20000 + 24000 = 44000
        self.assertEqual(valor_inventario(tienda=self.tienda), Decimal('44000'))

    def test_sin_stock_devuelve_cero(self):
        tienda_vacia = Tienda.objects.create(nombre_organizacion='Vacía', activa=True)
        self.assertEqual(valor_inventario(tienda=tienda_vacia), Decimal('0'))

    def test_global_sin_filtro(self):
        self.assertEqual(valor_inventario(), Decimal('44000'))
