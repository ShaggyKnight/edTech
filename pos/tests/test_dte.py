"""Tests de la emisión de DTE (Fase E).

Cubre el factory `get_emissor`, el `MockDteEmissor`, y la integración con
`procesar_venta` y `confirmar_pedido`. La política clave es que un fallo
del emisor NO debe romper la venta — la testeamos explícitamente.
"""

from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase, override_settings

from bodega.models import StockTienda, Tienda
from catalogo.models import Familia, Producto
from pos.dte import (
    DteEmissorError,
    DteResult,
    MockDteEmissor,
    OpenFacturaEmissor,
    emitir_si_corresponde,
    get_emissor,
)
from pos.models import ReciboVenta
from pos.services import ItemVenta, procesar_venta


class GetEmissorTests(TestCase):
    @override_settings(DTE_EMISSOR='mock')
    def test_default_es_mock(self):
        emissor = get_emissor()
        self.assertIsInstance(emissor, MockDteEmissor)

    @override_settings(DTE_EMISSOR='none')
    def test_none_devuelve_none(self):
        self.assertIsNone(get_emissor())

    @override_settings(DTE_EMISSOR='')
    def test_vacio_devuelve_none(self):
        self.assertIsNone(get_emissor())

    @override_settings(
        DTE_EMISSOR='openfactura',
        OPENFACTURA_API_KEY='', OPENFACTURA_RUT_EMISOR='',
    )
    def test_openfactura_sin_creds_falla(self):
        with self.assertRaises(DteEmissorError):
            get_emissor()

    @override_settings(
        DTE_EMISSOR='openfactura',
        OPENFACTURA_API_KEY='ABC',
        OPENFACTURA_RUT_EMISOR='12345678-9',
    )
    def test_openfactura_con_creds_instancia(self):
        emissor = get_emissor()
        self.assertIsInstance(emissor, OpenFacturaEmissor)
        self.assertEqual(emissor.rut_emisor, '12345678-9')


class MockEmissorTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.familia = Familia.objects.create(nombre='Perfumes')
        cls.tienda = Tienda.objects.create(nombre_organizacion='T', activa=True)

    def _recibo(self):
        return ReciboVenta.objects.create(
            canal=ReciboVenta.CANAL_PRESENCIAL,
            tienda=self.tienda,
            total=Decimal('10000'),
            estado=ReciboVenta.ESTADO_PAGADO,
        )

    def test_mock_genera_folio_consistente_con_pk(self):
        recibo = self._recibo()
        result = MockDteEmissor().emitir(recibo)
        self.assertEqual(result.folio, f'M{recibo.pk:08d}')
        self.assertIn('TED', result.timbre_xml)

    def test_emitir_si_corresponde_persiste_folio(self):
        recibo = self._recibo()
        with self.settings(DTE_EMISSOR='mock',
                           DTE_CANALES_HABILITADOS=['presencial', 'online']):
            result = emitir_si_corresponde(recibo)
        self.assertIsNotNone(result)
        recibo.refresh_from_db()
        self.assertEqual(recibo.dte_folio, f'M{recibo.pk:08d}')
        self.assertIn('TED', recibo.dte_timbre_xml)

    def test_no_emite_si_no_pagado(self):
        recibo = ReciboVenta.objects.create(
            canal=ReciboVenta.CANAL_PRESENCIAL,
            tienda=self.tienda,
            total=Decimal('10000'),
            estado=ReciboVenta.ESTADO_PENDIENTE,
        )
        with self.settings(DTE_EMISSOR='mock',
                           DTE_CANALES_HABILITADOS=['presencial', 'online']):
            self.assertIsNone(emitir_si_corresponde(recibo))
        recibo.refresh_from_db()
        self.assertEqual(recibo.dte_folio, '')

    def test_idempotente_no_reemite(self):
        """Si ya hay folio, no se vuelve a emitir."""
        recibo = self._recibo()
        recibo.dte_folio = 'M00000001'
        recibo.save()
        with self.settings(DTE_EMISSOR='mock',
                           DTE_CANALES_HABILITADOS=['presencial', 'online']):
            self.assertIsNone(emitir_si_corresponde(recibo))

    # ─── Filtro por canal (estrategia "online primero") ─────────────────

    def test_no_emite_si_canal_no_esta_habilitado(self):
        """Default DTE_CANALES_HABILITADOS=['online']: presencial NO emite."""
        recibo = self._recibo()  # canal=PRESENCIAL
        with self.settings(DTE_EMISSOR='mock',
                           DTE_CANALES_HABILITADOS=['online']):
            self.assertIsNone(emitir_si_corresponde(recibo))
        recibo.refresh_from_db()
        self.assertEqual(recibo.dte_folio, '')

    def test_emite_si_canal_online_habilitado(self):
        """Default DTE_CANALES_HABILITADOS=['online']: online SI emite."""
        recibo = ReciboVenta.objects.create(
            canal=ReciboVenta.CANAL_ONLINE,
            tienda=self.tienda,
            total=Decimal('10000'),
            estado=ReciboVenta.ESTADO_PAGADO,
        )
        with self.settings(DTE_EMISSOR='mock',
                           DTE_CANALES_HABILITADOS=['online']):
            result = emitir_si_corresponde(recibo)
        self.assertIsNotNone(result)
        recibo.refresh_from_db()
        self.assertTrue(recibo.dte_folio)

    def test_canales_habilitados_vacio_no_emite_nada(self):
        """Si la lista esta vacia, ni online ni presencial emiten."""
        recibo = ReciboVenta.objects.create(
            canal=ReciboVenta.CANAL_ONLINE,
            tienda=self.tienda,
            total=Decimal('10000'),
            estado=ReciboVenta.ESTADO_PAGADO,
        )
        with self.settings(DTE_EMISSOR='mock', DTE_CANALES_HABILITADOS=[]):
            self.assertIsNone(emitir_si_corresponde(recibo))

    def test_falla_de_emissor_no_rompe_y_no_guarda(self):
        recibo = self._recibo()

        class _Boom:
            provider = 'boom'
            def emitir(self, r):
                raise DteEmissorError('servicio caído')

        with patch('pos.dte.get_emissor', return_value=_Boom()), \
                self.settings(DTE_CANALES_HABILITADOS=['presencial', 'online']):
            result = emitir_si_corresponde(recibo)
        self.assertIsNone(result)
        recibo.refresh_from_db()
        self.assertEqual(recibo.dte_folio, '')
        # La venta sigue pagada — esa es la propiedad clave.
        self.assertEqual(recibo.estado, ReciboVenta.ESTADO_PAGADO)


@override_settings(
    PAYMENT_GATEWAY='mock',
    DTE_EMISSOR='mock',
    # Habilitamos ambos canales en este test suite: queremos validar que el
    # pipeline `procesar_venta` SI emite cuando todo esta configurado para
    # emitir. El test del filtro por canal va en MockEmissorTests.
    DTE_CANALES_HABILITADOS=['presencial', 'online'],
)
class ProcesarVentaConDteTests(TestCase):
    """Smoke: procesar_venta integra la emisión de DTE."""

    @classmethod
    def setUpTestData(cls):
        cls.familia = Familia.objects.create(nombre='Perfumes')
        cls.tienda = Tienda.objects.create(nombre_organizacion='T', activa=True)
        cls.producto = Producto.objects.create(
            familia=cls.familia, nombre='Perfume',
            precio_base=Decimal('15000'), tiene_variantes=False,
        )
        StockTienda.objects.create(tienda=cls.tienda, producto=cls.producto, cantidad=5)

    def test_venta_exitosa_emite_dte(self):
        recibo = procesar_venta(
            tienda=self.tienda,
            vendedor=None,
            items=[ItemVenta(
                tipo='p', item_id=self.producto.pk, cantidad=1,
                precio_unitario=Decimal('15000'), descuento_total=Decimal('0'),
            )],
            cliente_nombre='Test Cliente',
        )
        self.assertEqual(recibo.estado, ReciboVenta.ESTADO_PAGADO)
        self.assertEqual(recibo.dte_folio, f'M{recibo.pk:08d}')
        self.assertIn('TED', recibo.dte_timbre_xml)

    def test_venta_exitosa_aunque_emisor_falle(self):
        """Si el DTE falla, la venta sigue siendo válida."""
        class _Boom:
            provider = 'boom'
            def emitir(self, r):
                raise DteEmissorError('caído')

        with patch('pos.dte.get_emissor', return_value=_Boom()):
            recibo = procesar_venta(
                tienda=self.tienda,
                vendedor=None,
                items=[ItemVenta(
                    tipo='p', item_id=self.producto.pk, cantidad=1,
                    precio_unitario=Decimal('15000'), descuento_total=Decimal('0'),
                )],
                cliente_nombre='Test',
            )
        self.assertEqual(recibo.estado, ReciboVenta.ESTADO_PAGADO)
        self.assertEqual(recibo.dte_folio, '')  # no se emitió, pero la venta vive
