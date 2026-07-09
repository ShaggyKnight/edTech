"""Transferencia bancaria directa — pago manual como gateway activable.

Flujo: checkout elige `transferencia` → pedido PENDIENTE → pagina/correo
con datos de la cuenta → la dueña confirma el abono en Despacho → recien
ahi stock/boleta/cola. Anular si nunca llego la plata.
"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.roles import DESPACHADOR, OPERADOR
from bodega.models import StockTienda, Tienda
from catalogo.models import Familia, Producto
from ecommerce.gateways import get_gateways_activos
from pos.models import ReciboVenta

User = get_user_model()

DATOS_CUENTA = dict(
    TRANSFERENCIA_NOMBRE='Blanca Contreras',
    TRANSFERENCIA_RUT='12.345.678-9',
    TRANSFERENCIA_BANCO='BancoEstado',
    TRANSFERENCIA_TIPO_CUENTA='CuentaRUT',
    TRANSFERENCIA_CUENTA='12345678',
)


class _BaseTransferencia(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.tienda = Tienda.objects.create(nombre_organizacion='Online', activa=True)
        fam = Familia.objects.create(nombre='Perfumes')
        cls.producto = Producto.objects.create(
            familia=fam, nombre='Perfume Transferible',
            precio_base=Decimal('19990'), tiene_variantes=False,
        )
        cls.stock = StockTienda.objects.create(
            tienda=cls.tienda, producto=cls.producto, cantidad=3,
        )

    def setUp(self):
        self.override = self.settings(
            ECOMMERCE_TIENDA_ID=self.tienda.pk,
            ECOMMERCE_GATEWAYS_ACTIVOS=['transferencia'],
            **DATOS_CUENTA,
        )
        self.override.enable()

    def tearDown(self):
        self.override.disable()

    def _comprar(self):
        self.client.post(reverse('ecommerce:agregar'), {
            'tipo': 'p', 'item_id': self.producto.pk, 'cantidad': 1,
        })
        return self.client.post(reverse('ecommerce:checkout_iniciar'), {
            'cliente_nombre': 'Ana Transferencia',
            'cliente_email': 'ana@example.com',
            'cliente_telefono': '+56955443322',
            'gateway': 'transferencia',
        })


class GatewayActivableTests(TestCase):

    def test_sin_datos_bancarios_no_se_activa(self):
        with self.settings(ECOMMERCE_GATEWAYS_ACTIVOS=['transferencia'],
                           TRANSFERENCIA_NOMBRE='', TRANSFERENCIA_RUT='',
                           TRANSFERENCIA_CUENTA=''):
            nombres = [g.provider for g in get_gateways_activos()]
            self.assertNotIn('transferencia', nombres)

    def test_con_datos_se_activa(self):
        with self.settings(ECOMMERCE_GATEWAYS_ACTIVOS=['transferencia'],
                           **DATOS_CUENTA):
            nombres = [g.provider for g in get_gateways_activos()]
            self.assertIn('transferencia', nombres)


class CheckoutTransferenciaTests(_BaseTransferencia):

    def test_pedido_queda_pendiente_y_redirige_a_instrucciones(self):
        resp = self._comprar()
        self.assertEqual(resp.status_code, 302)
        recibo = ReciboVenta.objects.latest('pk')
        self.assertEqual(recibo.estado, ReciboVenta.ESTADO_PENDIENTE)
        self.assertEqual(recibo.payment_provider, 'transferencia')
        self.assertIn(f'/tienda/transferencia/{recibo.payment_reference}/',
                      resp['Location'])
        # El stock NO se descuenta hasta confirmar el abono.
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.cantidad, 3)

    def test_pagina_instrucciones_muestra_datos_y_limpia_carrito(self):
        resp = self._comprar()
        recibo = ReciboVenta.objects.latest('pk')
        pagina = self.client.get(resp['Location'])
        self.assertEqual(pagina.status_code, 200)
        cuerpo = pagina.content.decode()
        self.assertIn('Blanca Contreras', cuerpo)
        self.assertIn('12345678', cuerpo)          # nro de cuenta
        self.assertIn('BancoEstado', cuerpo)
        self.assertIn(f'Pedido #{recibo.pk}', cuerpo)  # referencia
        # Carrito limpio tras tomar el pedido.
        carrito = self.client.get(reverse('ecommerce:carrito'))
        self.assertNotContains(carrito, 'Perfume Transferible')

    def test_envia_email_con_instrucciones(self):
        self._comprar()
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('Datos para transferir', mail.outbox[0].subject)
        html = mail.outbox[0].alternatives[0][0]
        self.assertIn('12345678', html)

    def test_instrucciones_de_pedido_pagado_redirige_al_pedido(self):
        self._comprar()
        recibo = ReciboVenta.objects.latest('pk')
        ReciboVenta.objects.filter(pk=recibo.pk).update(
            estado=ReciboVenta.ESTADO_PAGADO)
        resp = self.client.get(reverse(
            'ecommerce:transferencia_instrucciones',
            args=[recibo.payment_reference]))
        self.assertRedirects(
            resp,
            reverse('ecommerce:pedido', args=[recibo.payment_reference]),
            fetch_redirect_response=False)


class ConfirmacionDespachoTests(_BaseTransferencia):

    def setUp(self):
        super().setUp()
        self._comprar()
        mail.outbox = []   # limpiar el correo de instrucciones
        self.recibo = ReciboVenta.objects.latest('pk')

        self.operadora = User.objects.create_user('blanca', password='x')
        self.operadora.groups.add(Group.objects.get(name=OPERADOR))
        self.despachador = User.objects.create_user('despacha', password='x')
        self.despachador.groups.add(Group.objects.get(name=DESPACHADOR))

    def test_tab_por_confirmar_lista_el_pedido(self):
        self.client.force_login(self.operadora)
        resp = self.client.get(reverse('despacho:cola') + '?estado=transferencias')
        self.assertContains(resp, f'#{self.recibo.pk}')
        self.assertContains(resp, 'Confirmar pago')
        self.assertEqual(resp.context['contadores']['transferencias'], 1)

    def test_confirmar_descuenta_stock_y_envia_boleta(self):
        self.client.force_login(self.operadora)
        resp = self.client.post(reverse(
            'despacho:confirmar_transferencia', args=[self.recibo.pk]))
        self.assertEqual(resp.status_code, 302)

        self.recibo.refresh_from_db()
        self.assertEqual(self.recibo.estado, ReciboVenta.ESTADO_PAGADO)
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.cantidad, 2)   # recien ahora
        # Boleta enviada al confirmar.
        asuntos = ' '.join(m.subject for m in mail.outbox)
        self.assertIn(f'#{self.recibo.pk}', asuntos)
        # Aparece en la cola de nuevos para despachar.
        cola = self.client.get(reverse('despacho:cola'))
        self.assertContains(cola, f'#{self.recibo.pk}')

    def test_despachador_puro_no_puede_confirmar(self):
        self.client.force_login(self.despachador)
        resp = self.client.post(reverse(
            'despacho:confirmar_transferencia', args=[self.recibo.pk]))
        # Rebota al login (user_passes_test) — nunca 302 a la cola.
        self.assertIn('/cuenta/login', resp['Location'])
        self.recibo.refresh_from_db()
        self.assertEqual(self.recibo.estado, ReciboVenta.ESTADO_PENDIENTE)

    def test_anular_cancela_sin_tocar_stock(self):
        self.client.force_login(self.operadora)
        resp = self.client.post(reverse(
            'despacho:anular_transferencia', args=[self.recibo.pk]))
        self.assertEqual(resp.status_code, 302)
        self.recibo.refresh_from_db()
        self.assertEqual(self.recibo.estado, ReciboVenta.ESTADO_CANCELADO)
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.cantidad, 3)

    def test_confirmar_sin_stock_queda_fallido(self):
        """El stock se evaporo (venta presencial) mientras esperaba la
        transferencia → NO se confirma: fallido para devolver la plata."""
        StockTienda.objects.filter(pk=self.stock.pk).update(cantidad=0)
        self.client.force_login(self.operadora)
        self.client.post(reverse(
            'despacho:confirmar_transferencia', args=[self.recibo.pk]))
        self.recibo.refresh_from_db()
        self.assertEqual(self.recibo.estado, ReciboVenta.ESTADO_FALLIDO)
