"""Tests del validador de RUT chileno + endpoint HTMX inline."""
from django.core.exceptions import ValidationError
from django.test import TestCase, SimpleTestCase
from django.urls import reverse

from ecommerce.validators import (
    calcular_dv, normalizar_rut, validar_rut_chileno,
)


class CalcularDvTests(SimpleTestCase):
    def test_dv_conocidos(self):
        # Ejemplos verificables con calculadora de RUT chilena.
        # 12345678 -> DV 5
        self.assertEqual(calcular_dv(12345678), '5')
        # 11111111 -> DV 1
        self.assertEqual(calcular_dv(11111111), '1')

    def test_dv_k(self):
        # 6 -> DV K (caso mas chico que da resto 1).
        # 10000013 -> K (caso de 8 digitos verificable a mano).
        self.assertEqual(calcular_dv(6), 'K')
        self.assertEqual(calcular_dv(10000013), 'K')

    def test_dv_cero(self):
        # 14 es el caso mas chico cuyo DV es 0.
        # 4*2 + 1*3 = 8 + 3 = 11. 11 % 11 = 0. 11 - 0 = 11 -> "0".
        self.assertEqual(calcular_dv(14), '0')
        self.assertEqual(calcular_dv(1000013), '0')


class NormalizarRutTests(SimpleTestCase):
    def test_quita_puntos_y_guiones(self):
        self.assertEqual(normalizar_rut('12.345.678-5'), '123456785')

    def test_mayusculiza_k(self):
        self.assertEqual(normalizar_rut('6680001-k'), '6680001K')

    def test_quita_espacios(self):
        self.assertEqual(normalizar_rut(' 12345678-5 '), '123456785')

    def test_vacio(self):
        self.assertEqual(normalizar_rut(''), '')
        self.assertEqual(normalizar_rut(None), '')


class ValidarRutChilenoTests(SimpleTestCase):
    def test_rut_valido_con_puntos_y_guion(self):
        self.assertEqual(validar_rut_chileno('12.345.678-5'), '12345678-5')

    def test_rut_valido_sin_separadores(self):
        self.assertEqual(validar_rut_chileno('123456785'), '12345678-5')

    def test_rut_con_k(self):
        # 10000013 -> DV=K (verificado con el algoritmo del modulo).
        self.assertEqual(validar_rut_chileno('10000013-K'), '10000013-K')
        # Minuscula tambien acepta.
        self.assertEqual(validar_rut_chileno('10000013-k'), '10000013-K')

    def test_rut_vacio_levanta(self):
        with self.assertRaisesMessage(ValidationError, 'Ingresá tu RUT'):
            validar_rut_chileno('')

    def test_rut_corto_levanta(self):
        with self.assertRaisesMessage(ValidationError, 'demasiado corto'):
            validar_rut_chileno('1')

    def test_rut_con_letras_levanta(self):
        with self.assertRaisesMessage(ValidationError, 'solo puede tener números'):
            validar_rut_chileno('abcdefg-5')

    def test_dv_incorrecto_levanta(self):
        # 12345678 tiene DV=5; probar con 0 falla.
        with self.assertRaisesMessage(ValidationError, 'RUT inválido'):
            validar_rut_chileno('12345678-0')

    def test_dv_invalido_no_numerico_ni_k(self):
        with self.assertRaisesMessage(ValidationError, 'verificador inválido'):
            validar_rut_chileno('12345678-Z')


class ValidarRutInlineEndpointTests(TestCase):
    """Endpoint HTMX que valida el RUT y devuelve fragment con clase."""

    def test_rut_valido_devuelve_field_msg_ok(self):
        resp = self.client.post(
            reverse('ecommerce:validar_rut_inline'),
            {'cliente_rut': '12.345.678-5'},
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn('field-msg-ok', body)
        self.assertIn('12345678-5', body)  # normalizado

    def test_rut_invalido_devuelve_field_msg_error(self):
        resp = self.client.post(
            reverse('ecommerce:validar_rut_inline'),
            {'cliente_rut': '12345678-0'},  # DV malo
        )
        body = resp.content.decode()
        self.assertIn('field-msg-error', body)
        self.assertIn('RUT inválido', body)

    def test_rut_vacio_devuelve_fragment_vacio(self):
        """Cuando el campo se borra, el mensaje desaparece."""
        resp = self.client.post(
            reverse('ecommerce:validar_rut_inline'),
            {'cliente_rut': ''},
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode().strip()
        self.assertNotIn('field-msg', body)

    def test_get_no_aceptado(self):
        resp = self.client.get(reverse('ecommerce:validar_rut_inline'))
        self.assertEqual(resp.status_code, 405)
