"""Tests del context processor `proxima_temporada_uniformes`.

Bug que motivo este context processor: el banner "ajustes sin costo
hasta marzo 2026" quedo hardcoded en HTML y vencio en mayo 2026.
Ahora la fecha se calcula dinamicamente.
"""
import datetime
from unittest import mock

from django.test import RequestFactory, TestCase

from edTech.context_processors import proxima_temporada_uniformes


class ProximaTemporadaUniformesTests(TestCase):
    def _ctx(self, fake_today):
        """Llama al context processor con `datetime.date.today` mockeado."""
        rf = RequestFactory()
        with mock.patch('edTech.context_processors.datetime') as m:
            # Mockear `datetime.date.today()`, mantener todo lo demas.
            m.date.today.return_value = fake_today
            m.date.side_effect = lambda *a, **kw: datetime.date(*a, **kw)
            return proxima_temporada_uniformes(rf.get('/'))

    def test_en_enero_apunta_al_marzo_del_mismo_ano(self):
        ctx = self._ctx(datetime.date(2027, 1, 15))
        self.assertEqual(ctx['ajustes_fecha_tope'], 'marzo 2027')
        self.assertEqual(ctx['ajustes_ano'], 2027)

    def test_en_febrero_apunta_al_marzo_del_mismo_ano(self):
        ctx = self._ctx(datetime.date(2027, 2, 28))
        self.assertEqual(ctx['ajustes_fecha_tope'], 'marzo 2027')

    def test_en_marzo_ya_apunta_al_proximo_ano(self):
        """En marzo el cutoff ya esta encima — empuja al ano siguiente
        para que el banner no diga una fecha que esta por vencerse."""
        ctx = self._ctx(datetime.date(2027, 3, 5))
        self.assertEqual(ctx['ajustes_fecha_tope'], 'marzo 2028')

    def test_en_mayo_apunta_al_proximo_marzo(self):
        """Caso real del bug: en mayo 2026 el banner decia 'marzo 2026'."""
        ctx = self._ctx(datetime.date(2026, 5, 14))
        self.assertEqual(ctx['ajustes_fecha_tope'], 'marzo 2027')

    def test_en_diciembre_apunta_al_marzo_siguiente(self):
        ctx = self._ctx(datetime.date(2026, 12, 31))
        self.assertEqual(ctx['ajustes_fecha_tope'], 'marzo 2027')

    def test_devuelve_short_form(self):
        ctx = self._ctx(datetime.date(2027, 4, 1))
        self.assertEqual(ctx['ajustes_fecha_tope_short'], 'mar 2028')
