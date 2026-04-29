"""Tests del CRUD de materiales y rendimientos — Fase Ñ.2."""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse

from bodega.models import Material, Rendimiento, StockMaterial, Bodega, Tienda
from bodega.services import resumen_produccion, resumen_produccion_global
from catalogo.models import Familia, Producto, ProductoVariante

User = get_user_model()


class MaterialesCrudTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.bodeguero = User.objects.create_user('bod', password='x')
        grupo, _ = Group.objects.get_or_create(name='bodeguero')
        cls.bodeguero.groups.add(grupo)

        cls.cajero = User.objects.create_user('caj', password='x')
        gc, _ = Group.objects.get_or_create(name='cajero')
        cls.cajero.groups.add(gc)

    def test_cajero_no_accede_a_materiales(self):
        self.client.force_login(self.cajero)
        resp = self.client.get(reverse('bodega:lista_materiales'))
        self.assertEqual(resp.status_code, 302)

    def test_bodeguero_si_accede(self):
        self.client.force_login(self.bodeguero)
        resp = self.client.get(reverse('bodega:lista_materiales'))
        self.assertEqual(resp.status_code, 200)

    def test_crear_material(self):
        self.client.force_login(self.bodeguero)
        resp = self.client.post(reverse('bodega:material_nuevo'), {
            'nombre': 'Tela test',
            'descripcion': 'Para testing',
            'proveedor': '',
            'costo_unitario_referencia': '40000',
            'activo': 'on',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp['Location'], reverse('bodega:lista_materiales'))
        m = Material.objects.get(nombre='Tela test')
        self.assertEqual(m.costo_unitario_referencia, Decimal('40000'))
        self.assertTrue(m.activo)

    def test_editar_material(self):
        m = Material.objects.create(
            nombre='Original', costo_unitario_referencia=Decimal('30000'),
        )
        self.client.force_login(self.bodeguero)
        resp = self.client.post(
            reverse('bodega:material_editar', args=[m.pk]),
            {'nombre': 'Renombrado', 'descripcion': '',
             'costo_unitario_referencia': '35000', 'activo': 'on'},
        )
        self.assertEqual(resp.status_code, 302)
        m.refresh_from_db()
        self.assertEqual(m.nombre, 'Renombrado')
        self.assertEqual(m.costo_unitario_referencia, Decimal('35000'))


class RendimientoCrudTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.bodeguero = User.objects.create_user('bod', password='x')
        grupo, _ = Group.objects.get_or_create(name='bodeguero')
        cls.bodeguero.groups.add(grupo)
        cls.fam = Familia.objects.create(nombre='Uniformes')
        cls.producto = Producto.objects.create(
            familia=cls.fam, nombre='Polera',
            precio_base=Decimal('10000'), tiene_variantes=True,
        )
        cls.var = ProductoVariante.objects.create(producto=cls.producto, sku='POL-M')
        cls.material = Material.objects.create(
            nombre='Tela X', costo_unitario_referencia=Decimal('25000'),
        )

    def test_crear_rendimiento(self):
        self.client.force_login(self.bodeguero)
        resp = self.client.post(
            reverse('bodega:rendimiento_nuevo', args=[self.material.pk]),
            {'variante': self.var.pk, 'unidades_por_rollo': 60},
        )
        self.assertEqual(resp.status_code, 302)
        r = Rendimiento.objects.get(material=self.material, variante=self.var)
        self.assertEqual(r.unidades_por_rollo, 60)

    def test_editar_rendimiento(self):
        r = Rendimiento.objects.create(
            material=self.material, variante=self.var, unidades_por_rollo=50,
        )
        self.client.force_login(self.bodeguero)
        resp = self.client.post(
            reverse('bodega:rendimiento_editar', args=[self.material.pk, r.pk]),
            {'variante': self.var.pk, 'unidades_por_rollo': 70},
        )
        self.assertEqual(resp.status_code, 302)
        r.refresh_from_db()
        self.assertEqual(r.unidades_por_rollo, 70)

    def test_borrar_rendimiento(self):
        r = Rendimiento.objects.create(
            material=self.material, variante=self.var, unidades_por_rollo=50,
        )
        self.client.force_login(self.bodeguero)
        resp = self.client.post(
            reverse('bodega:rendimiento_borrar', args=[self.material.pk, r.pk]),
        )
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(Rendimiento.objects.filter(pk=r.pk).exists())


class ResumenProduccionConCostosTests(TestCase):
    """Verifica que el ResumenProduccion calcule costo y margen potencial."""

    @classmethod
    def setUpTestData(cls):
        cls.tienda = Tienda.objects.create(nombre_organizacion='LV', activa=True)
        cls.bodega = Bodega.objects.create(tienda=cls.tienda, nombre='B')
        cls.material = Material.objects.create(
            nombre='Tela', costo_unitario_referencia=Decimal('40000'),
        )
        cls.fam = Familia.objects.create(nombre='Uniformes')
        cls.producto = Producto.objects.create(
            familia=cls.fam, nombre='Buzo',
            precio_base=Decimal('30000'), precio_costo=Decimal('12000'),
            tiene_variantes=True,
        )
        cls.var_m = ProductoVariante.objects.create(producto=cls.producto, sku='BZ-M')
        Rendimiento.objects.create(
            material=cls.material, variante=cls.var_m, unidades_por_rollo=50,
        )
        StockMaterial.objects.create(
            bodega=cls.bodega, material=cls.material, cantidad=2,
        )

    def test_costos_y_margen_calculados(self):
        # 2 rollos × 50 u/rollo = 100 unidades.
        # Ingreso potencial: 100 × $30.000 = $3.000.000.
        # Costo potencial: 100 × $12.000 = $1.200.000.
        # Margen potencial: $1.800.000.
        r = resumen_produccion(self.bodega)
        self.assertEqual(r.capacidad_unidades, 100)
        self.assertEqual(r.valor_potencial_total, Decimal('3000000'))
        self.assertEqual(r.costo_potencial_total, Decimal('1200000'))
        self.assertEqual(r.margen_potencial_total, Decimal('1800000'))

    def test_resumen_global_suma_bodegas(self):
        # Otra bodega con material adicional.
        b2 = Bodega.objects.create(tienda=self.tienda, nombre='B2')
        StockMaterial.objects.create(
            bodega=b2, material=self.material, cantidad=1,
        )
        # Total: 3 rollos × 50 = 150 unidades.
        global_r = resumen_produccion_global()
        self.assertEqual(global_r.capacidad_unidades, 150)
        self.assertEqual(global_r.margen_potencial_total, Decimal('2700000'))
