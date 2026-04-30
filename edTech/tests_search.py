"""Tests del helper edTech.search.normalize_text."""
from django.test import TestCase

from edTech.search import normalize_text


class NormalizeTextTests(TestCase):
    def test_lowercase(self):
        self.assertEqual(normalize_text('PERFUME'), 'perfume')

    def test_quita_acentos(self):
        self.assertEqual(normalize_text('Perfumé Avéllá'), 'perfume avella')

    def test_strip_y_n_tilde(self):
        self.assertEqual(normalize_text('  Año Nuevo  '), 'ano nuevo')

    def test_vacio_y_none(self):
        self.assertEqual(normalize_text(''), '')
        self.assertEqual(normalize_text(None), '')

    def test_caracteres_especiales(self):
        # Mantiene puntuación pero baja a minúsculas.
        self.assertEqual(normalize_text('Buzo SFJ — Talla M'), 'buzo sfj — talla m')
