"""Tests del helper EAN-13."""
from django.test import SimpleTestCase

from catalogo.barcode import (
    calcular_digito_ean13,
    generar_codigo_interno,
    parsear_codigo_interno,
    validar_ean13,
)


class EAN13Tests(SimpleTestCase):

    def test_calcular_digito_ean13_caso_conocido(self):
        # 400638133393 + check=1 → 4006381333931 (Nestlé Buitoni, ejemplo
        # común en docs de EAN-13).
        self.assertEqual(calcular_digito_ean13('400638133393'), '1')

    def test_calcular_digito_rechaza_no_numerico(self):
        with self.assertRaises(ValueError):
            calcular_digito_ean13('400638abc933')

    def test_calcular_digito_rechaza_largo_distinto(self):
        with self.assertRaises(ValueError):
            calcular_digito_ean13('123')

    def test_validar_ean13_ok(self):
        self.assertTrue(validar_ean13('4006381333931'))

    def test_validar_ean13_check_invalido(self):
        self.assertFalse(validar_ean13('4006381333930'))

    def test_validar_ean13_largo_invalido(self):
        self.assertFalse(validar_ean13('123'))
        self.assertFalse(validar_ean13('400638133393'))     # 12 digitos
        self.assertFalse(validar_ean13('40063813339312'))   # 14 digitos

    def test_validar_ean13_caracteres_no_numericos(self):
        self.assertFalse(validar_ean13('400638abc1234'))

    def test_validar_ean13_vacio_o_none(self):
        self.assertFalse(validar_ean13(''))
        self.assertFalse(validar_ean13(None))


class GenerarCodigoInternoTests(SimpleTestCase):

    def test_genera_codigo_para_producto(self):
        codigo = generar_codigo_interno('p', 5)
        self.assertEqual(len(codigo), 13)
        self.assertTrue(codigo.startswith('200'))
        self.assertEqual(codigo[3], '1')  # tipo producto
        self.assertEqual(codigo[4:12], '00000005')
        # El codigo completo es EAN-13 valido (check correcto).
        self.assertTrue(validar_ean13(codigo))

    def test_genera_codigo_para_variante(self):
        codigo = generar_codigo_interno('v', 123)
        self.assertEqual(codigo[3], '2')  # tipo variante
        self.assertEqual(codigo[4:12], '00000123')
        self.assertTrue(validar_ean13(codigo))

    def test_genera_codigos_distintos_para_pk_distintos(self):
        a = generar_codigo_interno('v', 1)
        b = generar_codigo_interno('v', 2)
        self.assertNotEqual(a, b)

    def test_producto_y_variante_con_mismo_pk_no_colisionan(self):
        self.assertNotEqual(
            generar_codigo_interno('p', 42),
            generar_codigo_interno('v', 42),
        )

    def test_tipo_invalido_rechaza(self):
        with self.assertRaises(ValueError):
            generar_codigo_interno('x', 1)

    def test_pk_fuera_de_rango_rechaza(self):
        with self.assertRaises(ValueError):
            generar_codigo_interno('p', 0)
        with self.assertRaises(ValueError):
            generar_codigo_interno('p', -5)
        with self.assertRaises(ValueError):
            generar_codigo_interno('p', 10 ** 9)

    def test_pk_grande_dentro_de_rango_ok(self):
        codigo = generar_codigo_interno('v', 99_999_999)
        self.assertTrue(validar_ean13(codigo))


class ParsearCodigoInternoTests(SimpleTestCase):

    def test_round_trip_producto(self):
        codigo = generar_codigo_interno('p', 42)
        self.assertEqual(parsear_codigo_interno(codigo), ('p', 42))

    def test_round_trip_variante(self):
        codigo = generar_codigo_interno('v', 987)
        self.assertEqual(parsear_codigo_interno(codigo), ('v', 987))

    def test_codigo_externo_devuelve_none(self):
        """Un EAN-13 real (Nestlé) no debería matchear como interno."""
        self.assertIsNone(parsear_codigo_interno('4006381333931'))

    def test_codigo_invalido_devuelve_none(self):
        self.assertIsNone(parsear_codigo_interno('1234567890123'))  # check malo
        self.assertIsNone(parsear_codigo_interno('abc'))
        self.assertIsNone(parsear_codigo_interno(''))

    def test_codigo_con_prefijo_pero_tipo_invalido(self):
        # 200 + 9 + 00000001 + check valido. Tipo '9' no esta definido.
        cuerpo = '200900000001'
        codigo = cuerpo + calcular_digito_ean13(cuerpo)
        self.assertIsNone(parsear_codigo_interno(codigo))


class RenderSvgTests(SimpleTestCase):

    def test_renderiza_svg_para_codigo_valido(self):
        from catalogo.barcode import render_svg_ean13, generar_codigo_interno
        svg = render_svg_ean13(generar_codigo_interno('v', 5))
        # Empieza directo con <svg, sin <?xml ni DOCTYPE.
        self.assertTrue(svg.startswith('<svg'), svg[:80])
        self.assertIn('</svg>', svg)

    def test_codigo_invalido_levanta(self):
        from catalogo.barcode import render_svg_ean13
        with self.assertRaises(ValueError):
            render_svg_ean13('abc')
