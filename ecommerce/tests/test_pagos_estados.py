"""Estados de pago, correos post-pago y simulador — regresiones de la
revision del 2026-09-28.

Cada clase cubre un bug que la suite no veia porque el gateway mock
nunca devuelve PENDIENTE ni reintentos:
  - PENDIENTE (Khipu conciliando, Mercado Pago en revision) cerraba el
    pedido como fallido y el webhook de pago posterior se ignoraba.
  - Tras un rechazo, el pago aprobado con otra tarjeta se ignoraba.
  - El webhook nunca mandaba boleta ni aviso; recargar el retorno los
    duplicaba.
  - Sin credenciales en prod, Khipu/Mercado Pago caian al simulador y
    aprobaban pedidos sin cobrar.
  - El token de Mercado Pago ("IBR-<pk>") dejaba recorrer pedidos ajenos.
  - La pagina del pedido decia "pagado" para cualquier estado.
"""
import uuid
from decimal import Decimal
from unittest import mock
from urllib.parse import parse_qs, urlparse

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.roles import OPERADOR
from bodega.models import MovimientoStock, StockTienda, Tienda
from catalogo.models import Familia, Producto
from ecommerce.cart import Cart
from ecommerce.gateways import get_gateway_default, get_gateways_activos
from ecommerce.gateways.base import WebhookResult
from ecommerce.services import aplicar_resultado_pago, confirmar_pedido
from pos.models import ReciboVenta, ReciboVentaDetalle
from pos.payments import (
    ESTADO_CANCELADO, ESTADO_FALLIDO, ESTADO_PAGADO, ESTADO_PENDIENTE,
    PaymentGatewayError, PaymentResult,
)

DUENA = 'duena@example.com'
DATOS_CUENTA = dict(
    TRANSFERENCIA_NOMBRE='Blanca Contreras',
    TRANSFERENCIA_RUT='12.345.678-9',
    TRANSFERENCIA_CUENTA='12345678',
)


def _resultado(estado, provider='khipu'):
    return PaymentResult(estado=estado, provider=provider, reference='ref-1')


class _Base(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.tienda = Tienda.objects.create(nombre_organizacion='Online', activa=True)
        fam = Familia.objects.create(nombre='Perfumes')
        cls.producto = Producto.objects.create(
            familia=fam, nombre='Perfume Prueba',
            precio_base=Decimal('10000'), tiene_variantes=False,
        )
        cls.stock = StockTienda.objects.create(
            tienda=cls.tienda, producto=cls.producto, cantidad=5,
        )

    def _pedido(self, *, estado=ReciboVenta.ESTADO_PENDIENTE, provider='khipu',
                referencia=None, **extra):
        recibo = ReciboVenta.objects.create(
            canal=ReciboVenta.CANAL_ONLINE, tienda=self.tienda,
            subtotal=Decimal('10000'), total=Decimal('10000'), estado=estado,
            payment_provider=provider,
            payment_reference=referencia or f'tok-{uuid.uuid4().hex}',
            payment_idempotency_key=str(uuid.uuid4()),
            cliente_nombre='Ana Prueba', cliente_email='ana@example.com',
            **extra,
        )
        ReciboVentaDetalle.objects.create(
            recibo=recibo, producto=self.producto, descripcion='Perfume Prueba',
            cantidad=1, precio_unitario=Decimal('10000'),
        )
        return recibo

    def _stock(self):
        self.stock.refresh_from_db()
        return self.stock.cantidad

    def _asuntos(self):
        return [m.subject for m in mail.outbox]

    def _boletas(self):
        return [s for s in self._asuntos() if s.startswith('Boleta #')]

    def _avisos_venta(self):
        return [s for s in self._asuntos() if 'Nueva venta' in s]


@override_settings(OWNER_NOTIFICATION_EMAIL=DUENA)
class TransicionesDePagoTests(_Base):

    def test_pendiente_no_cierra_el_pedido_y_el_webhook_despues_lo_paga(self):
        recibo = self._pedido(referencia='pay_1')
        # Cliente vuelve de Khipu con la transferencia "verifying".
        with mock.patch('ecommerce.gateways.khipu.KhipuGateway.confirmar_pago',
                        return_value=_resultado(ESTADO_PENDIENTE)):
            recibo = confirmar_pedido(token='pay_1')
        self.assertEqual(recibo.estado, ReciboVenta.ESTADO_PENDIENTE)
        self.assertEqual(self._stock(), 5)

        # Minutos despues, el webhook: acreditado.
        recibo = aplicar_resultado_pago(recibo, _resultado(ESTADO_PAGADO))
        self.assertEqual(recibo.estado, ReciboVenta.ESTADO_PAGADO)
        self.assertIsNotNone(recibo.pago_recibido_en)
        self.assertEqual(self._stock(), 4)
        self.assertEqual(len(self._boletas()), 1)
        self.assertEqual(len(self._avisos_venta()), 1)

    def test_rechazo_y_despues_pago_aprobado_queda_pagado(self):
        """Mercado Pago: tarjeta rechazada, el cliente paga con otra en la
        misma preferencia. El primer rechazo no puede perder la venta."""
        recibo = self._pedido(provider='mercadopago')
        recibo = aplicar_resultado_pago(recibo, _resultado(ESTADO_FALLIDO, 'mercadopago'))
        self.assertEqual(recibo.estado, ReciboVenta.ESTADO_FALLIDO)

        recibo = aplicar_resultado_pago(recibo, _resultado(ESTADO_PAGADO, 'mercadopago'))
        self.assertEqual(recibo.estado, ReciboVenta.ESTADO_PAGADO)
        self.assertEqual(self._stock(), 4)
        self.assertEqual(len(self._boletas()), 1)

    def test_retorno_de_pedido_rechazado_vuelve_a_consultar_la_pasarela(self):
        recibo = self._pedido(estado=ReciboVenta.ESTADO_FALLIDO, referencia='pay_2')
        with mock.patch('ecommerce.gateways.khipu.KhipuGateway.confirmar_pago',
                        return_value=_resultado(ESTADO_PAGADO)) as m_confirmar:
            recibo = confirmar_pedido(token='pay_2')
        m_confirmar.assert_called_once()
        self.assertEqual(recibo.estado, ReciboVenta.ESTADO_PAGADO)

    def test_pagado_es_terminal(self):
        recibo = self._pedido()
        aplicar_resultado_pago(recibo, _resultado(ESTADO_PAGADO))
        mail.outbox = []

        for estado in (ESTADO_FALLIDO, ESTADO_CANCELADO, ESTADO_PAGADO):
            recibo = aplicar_resultado_pago(recibo, _resultado(estado))
            self.assertEqual(recibo.estado, ReciboVenta.ESTADO_PAGADO)
        self.assertEqual(self._stock(), 4)          # un solo descuento
        self.assertEqual(MovimientoStock.objects.count(), 1)
        self.assertEqual(mail.outbox, [])           # sin correos repetidos

    def test_rechazo_o_anulacion_solo_cierran_un_pedido_pendiente(self):
        recibo = self._pedido()
        recibo = aplicar_resultado_pago(recibo, _resultado(ESTADO_CANCELADO))
        self.assertEqual(recibo.estado, ReciboVenta.ESTADO_CANCELADO)
        # Un FALLIDO posterior no pisa el cancelado.
        recibo = aplicar_resultado_pago(recibo, _resultado(ESTADO_FALLIDO))
        self.assertEqual(recibo.estado, ReciboVenta.ESTADO_CANCELADO)

    def test_pago_sin_stock_queda_por_devolver_y_avisa_una_sola_vez(self):
        StockTienda.objects.filter(pk=self.stock.pk).update(cantidad=0)
        recibo = self._pedido()

        recibo = aplicar_resultado_pago(recibo, _resultado(ESTADO_PAGADO))
        self.assertEqual(recibo.estado, ReciboVenta.ESTADO_FALLIDO)
        self.assertIsNotNone(recibo.pago_recibido_en)   # se cobro: por devolver
        alertas = [m for m in mail.outbox if 'devolver' in m.subject]
        self.assertEqual(len(alertas), 1)
        self.assertEqual(alertas[0].to, [DUENA])
        self.assertIn(f'#{recibo.pk}', alertas[0].subject)
        self.assertEqual(self._boletas(), [])

        # El webhook repetido (o con stock repuesto) no reabre ni re-avisa.
        StockTienda.objects.filter(pk=self.stock.pk).update(cantidad=5)
        recibo = aplicar_resultado_pago(recibo, _resultado(ESTADO_PAGADO))
        self.assertEqual(recibo.estado, ReciboVenta.ESTADO_FALLIDO)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(self._stock(), 5)

    @override_settings(ECOMMERCE_PERMITIR_SIMULADOR=False, MERCADOPAGO_ACCESS_TOKEN='')
    def test_confirmar_con_la_pasarela_desactivada_deja_el_pedido_como_esta(self):
        recibo = self._pedido(provider='mercadopago', referencia='IBR-x')
        recibo = confirmar_pedido(token='IBR-x')
        self.assertEqual(recibo.estado, ReciboVenta.ESTADO_PENDIENTE)


@override_settings(OWNER_NOTIFICATION_EMAIL=DUENA)
class CorreosPostPagoTests(_Base):

    def _webhook_pagado(self, recibo):
        falso = WebhookResult(recibo_pk=recibo.pk, handled=True,
                              payment_result=_resultado(ESTADO_PAGADO))
        with mock.patch('ecommerce.gateways.khipu.KhipuGateway.webhook',
                        return_value=falso):
            return self.client.post(
                reverse('ecommerce:pago_webhook', args=['khipu']),
                data=b'{}', content_type='application/json',
            )

    def test_webhook_pagado_manda_boleta_y_aviso_una_sola_vez(self):
        recibo = self._pedido()
        self.assertEqual(self._webhook_pagado(recibo).status_code, 200)
        self.assertEqual(self._webhook_pagado(recibo).status_code, 200)  # reintento

        recibo.refresh_from_db()
        self.assertEqual(recibo.estado, ReciboVenta.ESTADO_PAGADO)
        self.assertEqual(len(self._boletas()), 1)
        self.assertEqual(len(self._avisos_venta()), 1)

    def test_recargar_el_retorno_no_duplica_la_boleta(self):
        recibo = self._pedido(provider='mock', referencia='tok-retorno')
        url = reverse('ecommerce:checkout_retorno') + '?token_ws=tok-retorno'
        self.assertRedirects(
            self.client.get(url),
            reverse('ecommerce:pedido', args=['tok-retorno']),
            fetch_redirect_response=False,
        )
        self.client.get(url)   # recarga / boton atras

        recibo.refresh_from_db()
        self.assertEqual(recibo.estado, ReciboVenta.ESTADO_PAGADO)
        self.assertEqual(len(self._boletas()), 1)
        self.assertEqual(len(self._avisos_venta()), 1)

    def test_webhook_antes_del_retorno_igual_limpia_el_carrito_sin_reenviar(self):
        recibo = self._pedido(referencia='pay_rapido')
        session = self.client.session
        Cart(session).add_producto(self.producto.pk, cantidad=1)
        session.save()

        self._webhook_pagado(recibo)
        resp = self.client.get(reverse('ecommerce:checkout_retorno') + '?token_ws=pay_rapido')
        self.assertRedirects(resp, reverse('ecommerce:pedido', args=['pay_rapido']),
                             fetch_redirect_response=False)
        self.assertEqual(Cart(self.client.session).items_count, 0)
        self.assertEqual(len(self._boletas()), 1)

    def test_boleta_enlaza_a_la_pagina_del_pedido(self):
        recibo = self._pedido()
        with self.settings(SITE_URL='https://ideasboutique.cl'):
            aplicar_resultado_pago(recibo, _resultado(ESTADO_PAGADO))
        boleta = next(m for m in mail.outbox if m.subject.startswith('Boleta #'))
        url = f'https://ideasboutique.cl/tienda/pedido/{recibo.payment_reference}/'
        self.assertIn(f'href="{url}"', boleta.alternatives[0][0])
        self.assertIn(url, boleta.body)


@override_settings(ECOMMERCE_PERMITIR_SIMULADOR=False)
class SimuladorApagadoEnProdTests(_Base):

    @override_settings(
        ECOMMERCE_GATEWAYS_ACTIVOS=['mock', 'khipu', 'mercadopago', 'klap'],
        KHIPU_API_KEY='', MERCADOPAGO_ACCESS_TOKEN='',
        KLAP_COMMERCE_ID='', KLAP_API_KEY='',
    )
    def test_pasarelas_sin_credenciales_no_aparecen(self):
        self.assertEqual(get_gateways_activos(), [])

    @override_settings(ECOMMERCE_GATEWAYS_ACTIVOS=[])
    def test_sin_pasarelas_el_default_no_cae_al_simulador(self):
        with self.assertRaises(PaymentGatewayError):
            get_gateway_default()

    @override_settings(
        ECOMMERCE_GATEWAYS_ACTIVOS=['khipu', 'mercadopago'], ECOMMERCE_GATEWAY_DEFAULT='',
        KHIPU_API_KEY='k', KHIPU_SECRET='s', MERCADOPAGO_ACCESS_TOKEN='APP_USR-1',
        MERCADOPAGO_WEBHOOK_SECRET='w',
    )
    def test_con_credenciales_operan_en_modo_real(self):
        gws = get_gateways_activos()
        self.assertEqual([g.provider for g in gws], ['khipu', 'mercadopago'])
        self.assertFalse(any(g.mock_mode for g in gws))

    def test_simulador_de_pago_es_404(self):
        resp = self.client.get(reverse('ecommerce:mock_pago'),
                               {'token': 't', 'return_url': 'http://testserver/'})
        self.assertEqual(resp.status_code, 404)

    @override_settings(ECOMMERCE_GATEWAYS_ACTIVOS=['mercadopago'],
                       MERCADOPAGO_ACCESS_TOKEN='')
    def test_checkout_sin_pasarela_operativa_no_crea_pedidos(self):
        with self.settings(ECOMMERCE_TIENDA_ID=self.tienda.pk):
            self.client.post(reverse('ecommerce:agregar'), {
                'tipo': 'p', 'item_id': self.producto.pk, 'cantidad': 1})
            datos = {'cliente_nombre': 'Cliente', 'cliente_email': 'c@example.com'}
            # Forzando Mercado Pago y sin elegir (default).
            self.client.post(reverse('ecommerce:checkout_iniciar'),
                             {**datos, 'gateway': 'mercadopago'})
            self.client.post(reverse('ecommerce:checkout_iniciar'), datos)
        self.assertFalse(ReciboVenta.objects.exists())

    @override_settings(MERCADOPAGO_ACCESS_TOKEN='')
    def test_webhook_de_pasarela_desactivada_responde_503(self):
        resp = self.client.post(reverse('ecommerce:pago_webhook', args=['mercadopago']),
                                data=b'{}', content_type='application/json')
        self.assertEqual(resp.status_code, 503)


@override_settings(ECOMMERCE_GATEWAYS_ACTIVOS=['mercadopago'], MERCADOPAGO_ACCESS_TOKEN='')
class TokenDelPedidoTests(_Base):

    def test_pedidos_de_mercado_pago_no_se_pueden_recorrer_por_numero(self):
        with self.settings(ECOMMERCE_TIENDA_ID=self.tienda.pk):
            self.client.post(reverse('ecommerce:agregar'), {
                'tipo': 'p', 'item_id': self.producto.pk, 'cantidad': 1})
            resp = self.client.post(reverse('ecommerce:checkout_iniciar'), {
                'cliente_nombre': 'Clienta Real', 'cliente_email': 'clienta@example.com',
                'gateway': 'mercadopago'})
            q = parse_qs(urlparse(resp['Location']).query)
            resp = self.client.post(
                reverse('ecommerce:mock_pago')
                + f"?token={q['token'][0]}&return_url={q['return_url'][0]}",
                {'decision': 'aprobar'})
            self.client.get(resp['Location'])

        recibo = ReciboVenta.objects.get()
        self.assertEqual(recibo.estado, ReciboVenta.ESTADO_PAGADO)
        self.assertNotEqual(recibo.payment_reference, f'IBR-{recibo.pk:08d}')

        otro = self.client_class()   # visitante anonimo adivinando
        adivinado = otro.get(reverse('ecommerce:pedido', args=[f'IBR-{recibo.pk:08d}']))
        self.assertEqual(adivinado.status_code, 404)
        real = otro.get(reverse('ecommerce:pedido', args=[recibo.payment_reference]))
        self.assertContains(real, 'clienta@example.com')


class PaginaDelPedidoTests(_Base):

    def _ver(self, recibo):
        return self.client.get(reverse('ecommerce:pedido', args=[recibo.payment_reference]))

    def test_transferencia_pendiente_no_dice_pagado(self):
        recibo = self._pedido(provider='transferencia')
        resp = self._ver(recibo)
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, '¡Gracias por tu compra!')
        self.assertNotContains(resp, '<strong>pagado</strong>', html=False)
        self.assertNotContains(resp, 'Total pagado')
        self.assertContains(resp, 'esperando tu transferencia')
        self.assertContains(resp, reverse('ecommerce:transferencia_instrucciones',
                                          args=[recibo.payment_reference]))

    def test_pago_en_proceso_no_dice_pagado(self):
        resp = self._ver(self._pedido(provider='khipu'))
        self.assertContains(resp, 'confirmando tu pago')
        self.assertNotContains(resp, 'Total pagado')

    def test_pagado_dice_pagado(self):
        recibo = self._pedido()
        aplicar_resultado_pago(recibo, _resultado(ESTADO_PAGADO))
        resp = self._ver(recibo)
        self.assertContains(resp, '¡Gracias por tu compra!')
        self.assertContains(resp, 'Total pagado')

    def test_rechazado_dice_que_no_hubo_cargo(self):
        recibo = self._pedido(estado=ReciboVenta.ESTADO_FALLIDO)
        resp = self._ver(recibo)
        self.assertContains(resp, 'no se hizo ningún cargo')
        self.assertNotContains(resp, 'Total pagado')

    def test_por_devolver_dice_que_devolvemos_la_plata(self):
        StockTienda.objects.filter(pk=self.stock.pk).update(cantidad=0)
        recibo = self._pedido()
        aplicar_resultado_pago(recibo, _resultado(ESTADO_PAGADO))
        resp = self._ver(recibo)
        self.assertContains(resp, 'Recibimos tu pago')
        self.assertNotContains(resp, 'no se hizo ningún cargo')

    def test_retorno_de_pago_sin_stock_no_dice_que_no_se_cobro(self):
        StockTienda.objects.filter(pk=self.stock.pk).update(cantidad=0)
        recibo = self._pedido(provider='mock', referencia='tok-sin-stock')
        resp = self.client.get(reverse('ecommerce:checkout_retorno') + '?token_ws=tok-sin-stock')
        self.assertContains(resp, 'Recibimos tu pago')
        self.assertNotContains(resp, 'no se te cobró nada')
        recibo.refresh_from_db()
        self.assertEqual(recibo.estado, ReciboVenta.ESTADO_FALLIDO)


class DespachoSoloPedidosPagadosTests(_Base):

    def setUp(self):
        operadora = get_user_model().objects.create_user('blanca', password='x')
        operadora.groups.add(Group.objects.get(name=OPERADOR))
        self.client.force_login(operadora)

    def test_no_se_puede_despachar_un_pedido_sin_pagar(self):
        recibo = self._pedido(provider='transferencia')
        self.client.post(reverse('despacho:marcar_despachado', args=[recibo.pk]))
        recibo.refresh_from_db()
        self.assertIsNone(recibo.despachado_en)

    def test_detalle_de_pedido_sin_pagar_no_ofrece_despachar(self):
        recibo = self._pedido(provider='transferencia')
        resp = self.client.get(reverse('despacho:detalle', args=[recibo.pk]))
        self.assertContains(resp, 'ESPERANDO TRANSFERENCIA')
        self.assertNotContains(resp, 'Marcar como despachado')
        self.assertNotContains(resp, 'EN COLA')

    def test_detalle_de_pago_por_devolver_lo_dice(self):
        StockTienda.objects.filter(pk=self.stock.pk).update(cantidad=0)
        recibo = self._pedido()
        aplicar_resultado_pago(recibo, _resultado(ESTADO_PAGADO))
        resp = self.client.get(reverse('despacho:detalle', args=[recibo.pk]))
        self.assertContains(resp, 'PAGO POR DEVOLVER')
        self.assertNotContains(resp, 'Marcar como despachado')

    def test_pedido_pagado_si_se_despacha(self):
        recibo = self._pedido()
        aplicar_resultado_pago(recibo, _resultado(ESTADO_PAGADO))
        self.client.post(reverse('despacho:marcar_despachado', args=[recibo.pk]))
        recibo.refresh_from_db()
        self.assertIsNotNone(recibo.despachado_en)


class CheckoutYSimuladorTests(_Base):

    @override_settings(ECOMMERCE_GATEWAYS_ACTIVOS=['mock', 'transferencia'], **DATOS_CUENTA)
    def test_error_en_el_formulario_conserva_el_medio_de_pago_elegido(self):
        with self.settings(ECOMMERCE_TIENDA_ID=self.tienda.pk):
            self.client.post(reverse('ecommerce:agregar'), {
                'tipo': 'p', 'item_id': self.producto.pk, 'cantidad': 1})
            # Sin email ni celular: el formulario vuelve con error.
            resp = self.client.post(reverse('ecommerce:checkout_iniciar'), {
                'cliente_nombre': 'Ana', 'gateway': 'transferencia'})
        self.assertEqual(resp.status_code, 400)
        cuerpo = resp.content.decode()
        self.assertIn('name="gateway" value="transferencia"', cuerpo)
        seleccionado = cuerpo.split('value="transferencia"', 1)[1].split('>', 1)[0]
        self.assertIn('checked', seleccionado)

    @override_settings(ECOMMERCE_GATEWAYS_ACTIVOS=['transferencia'], **DATOS_CUENTA)
    def test_volver_a_las_instrucciones_no_borra_un_carrito_nuevo(self):
        with self.settings(ECOMMERCE_TIENDA_ID=self.tienda.pk):
            self.client.post(reverse('ecommerce:agregar'), {
                'tipo': 'p', 'item_id': self.producto.pk, 'cantidad': 1})
            resp = self.client.post(reverse('ecommerce:checkout_iniciar'), {
                'cliente_nombre': 'Ana', 'cliente_email': 'ana@example.com',
                'gateway': 'transferencia'})
            instrucciones = resp['Location']
            self.client.get(instrucciones)   # 1ra visita: vacia el carrito
            self.assertEqual(Cart(self.client.session).items_count, 0)

            # Compra otra cosa y vuelve a ver los datos para transferir.
            self.client.post(reverse('ecommerce:agregar'), {
                'tipo': 'p', 'item_id': self.producto.pk, 'cantidad': 2})
            self.client.get(instrucciones)
        self.assertEqual(Cart(self.client.session).items_count, 2)

    @override_settings(ECOMMERCE_GATEWAYS_ACTIVOS=['mock'])
    def test_simulador_no_redirige_a_otro_sitio(self):
        resp = self.client.get(reverse('ecommerce:mock_pago'), {
            'token': 't', 'return_url': 'https://sitio-malo.example/robar'})
        self.assertEqual(resp.status_code, 400)
