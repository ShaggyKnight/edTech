"""Tests de bodega: compra de materiales, recepción de lotes, capacidad."""

from decimal import Decimal

from django.test import TestCase

from bodega.models import (
    Bodega,
    Material,
    MovimientoMaterial,
    MovimientoStock,
    Proveedor,
    Rendimiento,
    StockMaterial,
    StockTienda,
    Tienda,
)
from bodega.services import (
    LineaProduccion,
    StockMaterialInsuficiente,
    capacidad_por_variante,
    comprar_material,
    recibir_lote,
    resumen_produccion,
)
from catalogo.models import Atributo, Familia, Producto, ProductoVariante, ValorAtributo
from contabilidad.models import MovimientoCaja
from contabilidad.services import valor_inventario


class ComprarMaterialTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tienda = Tienda.objects.create(nombre_organizacion='Ideas LV', activa=True)
        cls.bodega = Bodega.objects.create(tienda=cls.tienda, nombre='Bodega LV')
        cls.proveedor = Proveedor.objects.create(
            nombre_proveedor='Textil Sur', rut_proveedor='99999999-9',
        )
        cls.material = Material.objects.create(
            nombre='Tela buzo SFJ', proveedor=cls.proveedor,
            costo_unitario_referencia=Decimal('40000'),
        )

    def test_comprar_suma_stock_y_registra_egreso(self):
        mov = comprar_material(
            material=self.material,
            bodega=self.bodega,
            cantidad=5,
            costo_total=Decimal('210000'),
            tienda_caja=self.tienda,
            referencia='Factura 1234',
        )
        # Stock de material subió a 5.
        stock = StockMaterial.objects.get(bodega=self.bodega, material=self.material)
        self.assertEqual(stock.cantidad, 5)
        # MovimientoMaterial ENTRADA con costo total real.
        self.assertEqual(mov.tipo, MovimientoMaterial.ENTRADA)
        self.assertEqual(mov.cantidad, 5)
        self.assertEqual(mov.costo_total, Decimal('210000'))
        # Asiento contable: salida de caja por la compra.
        salida = MovimientoCaja.objects.get(tipo=MovimientoCaja.SALIDA)
        self.assertEqual(salida.monto, Decimal('210000'))
        self.assertIn('Tela buzo SFJ', salida.concepto)

    def test_comprar_acumula_sobre_stock_existente(self):
        comprar_material(
            material=self.material, bodega=self.bodega, cantidad=3,
            costo_total=Decimal('120000'), tienda_caja=self.tienda,
        )
        comprar_material(
            material=self.material, bodega=self.bodega, cantidad=2,
            costo_total=Decimal('90000'), tienda_caja=self.tienda,
        )
        stock = StockMaterial.objects.get(bodega=self.bodega, material=self.material)
        self.assertEqual(stock.cantidad, 5)
        # Dos compras, dos salidas de caja.
        self.assertEqual(MovimientoCaja.objects.filter(tipo=MovimientoCaja.SALIDA).count(), 2)

    def test_costo_total_cero_no_genera_egreso(self):
        """Aporte/regalo: rollos sin costo no producen MovimientoCaja."""
        comprar_material(
            material=self.material, bodega=self.bodega, cantidad=1,
            costo_total=Decimal('0'), tienda_caja=self.tienda,
        )
        self.assertFalse(MovimientoCaja.objects.exists())

    def test_cantidad_invalida_falla(self):
        with self.assertRaises(ValueError):
            comprar_material(
                material=self.material, bodega=self.bodega, cantidad=0,
                costo_total=Decimal('0'), tienda_caja=self.tienda,
            )


class RecibirLoteTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tienda = Tienda.objects.create(nombre_organizacion='Ideas LV', activa=True)
        cls.bodega = Bodega.objects.create(tienda=cls.tienda, nombre='Bodega LV')
        cls.material = Material.objects.create(
            nombre='Tela buzo SFJ', costo_unitario_referencia=Decimal('40000'),
        )
        cls.familia = Familia.objects.create(nombre='Uniformes Escolares')
        cls.producto = Producto.objects.create(
            familia=cls.familia, nombre='Buzo SFJ',
            precio_base=Decimal('25000'), tiene_variantes=True,
        )
        cls.atr_talla = Atributo.objects.create(nombre='Talla')
        cls.val_m = ValorAtributo.objects.create(atributo=cls.atr_talla, valor='M')
        cls.val_xl = ValorAtributo.objects.create(atributo=cls.atr_talla, valor='XL')
        cls.var_m = ProductoVariante.objects.create(producto=cls.producto, sku='BUZO-SFJ-M')
        cls.var_m.valores.add(cls.val_m)
        cls.var_xl = ProductoVariante.objects.create(producto=cls.producto, sku='BUZO-SFJ-XL')
        cls.var_xl.valores.add(cls.val_xl)

    def _con_stock(self, rollos: int):
        StockMaterial.objects.create(
            bodega=self.bodega, material=self.material, cantidad=rollos,
        )

    def test_recibir_descuenta_material_y_suma_producto(self):
        self._con_stock(3)
        recibir_lote(
            material=self.material,
            bodega=self.bodega,
            rollos_consumidos=2,
            lineas=[
                LineaProduccion(variante_id=self.var_m.pk, cantidad=80),
                LineaProduccion(variante_id=self.var_xl.pk, cantidad=40),
            ],
            tienda=self.tienda,
            costo_confeccion=Decimal('360000'),
            referencia='Lote A',
        )
        # Material: -2 rollos.
        self.assertEqual(
            StockMaterial.objects.get(bodega=self.bodega, material=self.material).cantidad, 1,
        )
        # StockTienda: 80 talla M, 40 talla XL.
        self.assertEqual(
            StockTienda.objects.get(tienda=self.tienda, variante=self.var_m).cantidad, 80,
        )
        self.assertEqual(
            StockTienda.objects.get(tienda=self.tienda, variante=self.var_xl).cantidad, 40,
        )
        # MovimientoStock auditando ambas entradas.
        self.assertEqual(
            MovimientoStock.objects.filter(tipo=MovimientoStock.ENTRADA).count(), 2,
        )
        # MovimientoMaterial.SALIDA con costo_total=0.
        mov = MovimientoMaterial.objects.get(tipo=MovimientoMaterial.SALIDA)
        self.assertEqual(mov.cantidad, 2)
        self.assertEqual(mov.costo_total, Decimal('0'))
        # MovimientoCaja.SALIDA por costo de confección (incluye accesorios).
        salida = MovimientoCaja.objects.get(tipo=MovimientoCaja.SALIDA)
        self.assertEqual(salida.monto, Decimal('360000'))
        self.assertIn('Confección', salida.concepto)

    def test_sin_stock_falla_y_revierte(self):
        self._con_stock(1)
        with self.assertRaises(StockMaterialInsuficiente):
            recibir_lote(
                material=self.material,
                bodega=self.bodega,
                rollos_consumidos=2,
                lineas=[LineaProduccion(variante_id=self.var_m.pk, cantidad=50)],
                tienda=self.tienda,
                costo_confeccion=Decimal('100000'),
            )
        # Nada de side-effects: rollback completo.
        self.assertEqual(
            StockMaterial.objects.get(material=self.material).cantidad, 1,
        )
        self.assertFalse(StockTienda.objects.exists())
        self.assertFalse(MovimientoStock.objects.exists())
        self.assertFalse(MovimientoMaterial.objects.exists())
        self.assertFalse(MovimientoCaja.objects.exists())

    def test_sin_filas_de_material_levanta_insuficiente(self):
        with self.assertRaises(StockMaterialInsuficiente):
            recibir_lote(
                material=self.material, bodega=self.bodega,
                rollos_consumidos=1,
                lineas=[LineaProduccion(variante_id=self.var_m.pk, cantidad=50)],
                tienda=self.tienda, costo_confeccion=Decimal('0'),
            )


class CapacidadYValorPotencialTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tienda = Tienda.objects.create(nombre_organizacion='Ideas LV', activa=True)
        cls.bodega = Bodega.objects.create(tienda=cls.tienda, nombre='B')
        cls.material = Material.objects.create(
            nombre='Tela buzo', costo_unitario_referencia=Decimal('40000'),
        )
        cls.fam = Familia.objects.create(nombre='Uniformes Escolares')
        cls.producto = Producto.objects.create(
            familia=cls.fam, nombre='Buzo SFJ',
            precio_base=Decimal('30000'), tiene_variantes=True,
        )
        cls.var_m = ProductoVariante.objects.create(producto=cls.producto, sku='BZ-M')
        cls.var_xl = ProductoVariante.objects.create(producto=cls.producto, sku='BZ-XL')
        Rendimiento.objects.create(material=cls.material, variante=cls.var_m, unidades_por_rollo=50)
        Rendimiento.objects.create(material=cls.material, variante=cls.var_xl, unidades_por_rollo=35)

    def test_capacidad_es_rollos_por_rendimiento(self):
        StockMaterial.objects.create(bodega=self.bodega, material=self.material, cantidad=3)
        cap = {c.variante_id: c for c in capacidad_por_variante(self.bodega)}
        self.assertEqual(cap[self.var_m.pk].capacidad, 150)   # 3 × 50
        self.assertEqual(cap[self.var_xl.pk].capacidad, 105)  # 3 × 35

    def test_sin_stock_capacidad_es_cero(self):
        cap = {c.variante_id: c for c in capacidad_por_variante(self.bodega)}
        self.assertEqual(cap[self.var_m.pk].capacidad, 0)

    def test_resumen_produccion_calcula_valor_total(self):
        StockMaterial.objects.create(bodega=self.bodega, material=self.material, cantidad=2)
        resumen = resumen_produccion(self.bodega)
        # 2 × 50 + 2 × 35 = 170 unidades, todas a $30000 → $5.100.000
        self.assertEqual(resumen.valor_potencial_total, Decimal('5100000'))
        # 2 rollos × $40.000 referencia → $80.000
        self.assertEqual(resumen.valor_materiales, Decimal('80000'))


class ValorInventarioConMaterialesTests(TestCase):
    """`valor_inventario` extendido en Fase K ahora incluye rollos en bodega."""

    @classmethod
    def setUpTestData(cls):
        cls.tienda = Tienda.objects.create(nombre_organizacion='Ideas LV', activa=True)
        cls.bodega = Bodega.objects.create(tienda=cls.tienda, nombre='B')
        cls.fam = Familia.objects.create(nombre='Perfumes')
        cls.producto = Producto.objects.create(
            familia=cls.fam, nombre='P30',
            precio_base=Decimal('15000'), precio_costo=Decimal('5000'),
            tiene_variantes=False,
        )
        cls.material = Material.objects.create(
            nombre='Fleece', costo_unitario_referencia=Decimal('40000'),
        )

    def test_suma_productos_terminados_y_rollos(self):
        StockTienda.objects.create(tienda=self.tienda, producto=self.producto, cantidad=4)
        StockMaterial.objects.create(bodega=self.bodega, material=self.material, cantidad=3)
        # 4 × $5000 + 3 × $40000 = $20.000 + $120.000 = $140.000
        self.assertEqual(valor_inventario(self.tienda), Decimal('140000'))

    def test_filtro_por_tienda_solo_incluye_sus_bodegas(self):
        otra = Tienda.objects.create(nombre_organizacion='Otra', activa=True)
        Bodega.objects.create(tienda=otra, nombre='Bx')
        StockMaterial.objects.create(bodega=self.bodega, material=self.material, cantidad=2)
        # Sólo nuestros materiales: 2 × 40000 = 80000
        self.assertEqual(valor_inventario(self.tienda), Decimal('80000'))
        self.assertEqual(valor_inventario(otra), Decimal('0'))
