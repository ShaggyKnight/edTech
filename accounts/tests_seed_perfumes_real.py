"""Tests del management command `seed_perfumes_real`.

Cubre: parser de formatos, idempotencia, precios coherentes.
"""
from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from catalogo.models import (
    Atributo, Familia, Producto, ProductoVariante, ValorAtributo,
)


class ParseFormatosTests(TestCase):
    """Unidades del parser — sin tocar DB."""

    def setUp(self):
        from accounts.management.commands.seed_perfumes_real import parse_formatos
        self.parse = parse_formatos

    def test_caso_basico_edt(self):
        vols, concs = self.parse('30ml, 50ml, 100ml (EDT)')
        self.assertEqual(vols, [30, 50, 100])
        self.assertEqual(concs, ['Eau de Toilette'])

    def test_caso_edp(self):
        vols, concs = self.parse('100ml (EDP)')
        self.assertEqual(vols, [100])
        self.assertEqual(concs, ['Eau de Parfum'])

    def test_body_spray(self):
        vols, concs = self.parse('200ml, 250ml (Body Spray)')
        self.assertEqual(vols, [200, 250])
        self.assertEqual(concs, ['Body Spray'])

    def test_doble_concentracion(self):
        """'50ml, 100ml (EDT/EDP)' → 2 concentraciones distintas."""
        vols, concs = self.parse('50ml, 100ml (EDT/EDP)')
        self.assertEqual(vols, [50, 100])
        self.assertEqual(set(concs), {'Eau de Toilette', 'Eau de Parfum'})

    def test_string_con_punto_final(self):
        vols, concs = self.parse('30ml, 50ml (EDT).')
        self.assertEqual(vols, [30, 50])
        self.assertEqual(concs, ['Eau de Toilette'])

    def test_formato_invalido(self):
        vols, concs = self.parse('formato raro sin parens')
        self.assertEqual(vols, [])
        self.assertEqual(concs, [])

    def test_volumen_con_espacio(self):
        vols, _ = self.parse('30 ml, 50 ml (EDT)')
        self.assertEqual(vols, [30, 50])


class PrecioReferencialTests(TestCase):
    def setUp(self):
        from accounts.management.commands.seed_perfumes_real import precio_referencial
        self.precio = precio_referencial

    def test_edp_mas_caro_que_edt_mismo_volumen(self):
        edt_50 = self.precio(50, 'Eau de Toilette')
        edp_50 = self.precio(50, 'Eau de Parfum')
        self.assertGreater(edp_50, edt_50)

    def test_mayor_volumen_mas_caro(self):
        edt_30 = self.precio(30, 'Eau de Toilette')
        edt_100 = self.precio(100, 'Eau de Toilette')
        self.assertGreater(edt_100, edt_30)

    def test_body_spray_es_el_mas_barato(self):
        bs = self.precio(200, 'Body Spray')
        edt = self.precio(50, 'Eau de Toilette')
        self.assertLess(bs, edt)

    def test_volumen_no_exacto_interpola(self):
        """Si el volumen no esta en la tabla (ej: 95ml), devuelve el
        precio del mas cercano (90ml o 100ml). NO crashea."""
        precio = self.precio(95, 'Eau de Toilette')
        self.assertGreater(precio, Decimal('0'))


class SeedPerfumesRealCommandTests(TestCase):
    """Tests de integracion del command."""

    def test_corre_sin_errores(self):
        out = StringIO()
        call_command('seed_perfumes_real', stdout=out)
        self.assertIn('Carga de perfumes reales', out.getvalue())
        # Se crearon productos.
        self.assertGreater(Producto.objects.count(), 30)
        # Familia Perfumes existe.
        self.assertTrue(Familia.objects.filter(nombre='Perfumes').exists())
        # Atributos creados.
        self.assertTrue(Atributo.objects.filter(nombre='Volumen').exists())
        self.assertTrue(Atributo.objects.filter(nombre='Concentración').exists())

    def test_es_idempotente(self):
        """Correrlo dos veces no duplica nada."""
        call_command('seed_perfumes_real', stdout=StringIO())
        n_prod_1 = Producto.objects.count()
        n_var_1 = ProductoVariante.objects.count()

        call_command('seed_perfumes_real', stdout=StringIO())
        n_prod_2 = Producto.objects.count()
        n_var_2 = ProductoVariante.objects.count()

        self.assertEqual(n_prod_1, n_prod_2)
        self.assertEqual(n_var_1, n_var_2)

    def test_solo_mujer_no_carga_hombres(self):
        call_command('seed_perfumes_real', '--solo-mujer', stdout=StringIO())
        # Productos especificamente masculinos NO deberian existir.
        self.assertFalse(Producto.objects.filter(nombre='Polo Red (Ralph Lauren)').exists())
        self.assertFalse(Producto.objects.filter(nombre='Armani Code').exists())
        # Producto especificamente femenino SI deberia existir.
        self.assertTrue(Producto.objects.filter(nombre='Tous Gold').exists())

    def test_doble_concentracion_genera_dos_grupos_de_variantes(self):
        """Bouquet Rose: '50ml, 100ml (EDP/EDT)' → 2 vols × 2 concs = 4 variantes."""
        call_command('seed_perfumes_real', stdout=StringIO())
        bouquet = Producto.objects.get(nombre='Bouquet Rose')
        self.assertEqual(bouquet.variantes.count(), 4)
        # Verificar combos.
        skus = set(bouquet.variantes.values_list('sku', flat=True))
        self.assertEqual(len(skus), 4)

    def test_marvelle_aparece_una_sola_vez(self):
        """En el CSV original Marvelle aparece dos veces — get_or_create dedupea."""
        call_command('seed_perfumes_real', stdout=StringIO())
        marvelles = Producto.objects.filter(nombre='Marvelle Women')
        self.assertEqual(marvelles.count(), 1)

    def test_variante_tiene_volumen_y_concentracion(self):
        call_command('seed_perfumes_real', stdout=StringIO())
        tous = Producto.objects.get(nombre='Tous Gold')
        # Tous Gold: 30ml, 50ml, 90ml (EDP) → 3 variantes
        self.assertEqual(tous.variantes.count(), 3)
        # Cada variante tiene 2 valores: volumen + concentracion.
        for v in tous.variantes.all():
            atrs = {val.atributo.nombre for val in v.valores.all()}
            self.assertEqual(atrs, {'Volumen', 'Concentración'})

    def test_sku_es_unico_y_estable(self):
        """SKU se genera deterministicamente. Si corre 2 veces el mismo
        SKU debe existir y no se duplica."""
        call_command('seed_perfumes_real', stdout=StringIO())
        skus_1 = set(ProductoVariante.objects.values_list('sku', flat=True))
        call_command('seed_perfumes_real', stdout=StringIO())
        skus_2 = set(ProductoVariante.objects.values_list('sku', flat=True))
        self.assertEqual(skus_1, skus_2)
        # SKU bien formado: empieza con PERF- y tiene 3+ piezas.
        for sku in skus_1:
            self.assertTrue(sku.startswith('PERF-'))
            self.assertGreaterEqual(sku.count('-'), 3)

    def test_update_precios_reescribe_precios(self):
        """Si una variante tiene precio modificado a mano, --update-precios
        lo vuelve al valor referencial."""
        call_command('seed_perfumes_real', stdout=StringIO())
        v = ProductoVariante.objects.first()
        v.precio_override = Decimal('99999')
        v.save()

        call_command('seed_perfumes_real', '--update-precios', stdout=StringIO())
        v.refresh_from_db()
        self.assertNotEqual(v.precio_override, Decimal('99999'))

    def test_sin_update_precios_respeta_precios_manuales(self):
        """Sin la flag, los precios editados a mano se mantienen."""
        call_command('seed_perfumes_real', stdout=StringIO())
        v = ProductoVariante.objects.first()
        precio_manual = Decimal('42424')
        v.precio_override = precio_manual
        v.save()

        call_command('seed_perfumes_real', stdout=StringIO())  # sin flag
        v.refresh_from_db()
        self.assertEqual(v.precio_override, precio_manual)
