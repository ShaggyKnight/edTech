"""Ley 21.719 (datos personales): textos legales, consentimiento de
cookies, derechos del titular (acceso, portabilidad, supresion) y
politica de conservacion.
"""
import io
import json
import os
import tempfile
import uuid
from datetime import timedelta
from decimal import Decimal

from axes.models import AccessLog
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser, Group
from django.core.management import CommandError, call_command
from django.http import HttpResponse
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.roles import OPERADOR
from bodega.models import StockTienda, Tienda
from catalogo.models import Familia, Producto, ProductoVariante, Resena
from ecommerce.models import AvisoStockReposicion
from ecommerce.whatsapp import _enmascarar
from pos.models import ReciboVenta, ReciboVentaDetalle

User = get_user_model()
TRACKERS = dict(CLARITY_PROJECT_ID='clar1ty', GOOGLE_TAG_ID='G-TEST123', META_PIXEL_ID='98765')
SIN_TRACKERS = dict(CLARITY_PROJECT_ID='', GOOGLE_TAG_ID='', META_PIXEL_ID='')


class _ConDatos(TestCase):
    """Una clienta con cuenta, pedidos, un aviso de reposicion y una resena."""

    @classmethod
    def setUpTestData(cls):
        cls.tienda = Tienda.objects.create(nombre_organizacion='Online', activa=True)
        fam = Familia.objects.create(nombre='Perfumes')
        cls.producto = Producto.objects.create(
            familia=fam, nombre='Perfume Ana', precio_base=Decimal('10000'),
            tiene_variantes=True,
        )
        cls.variante = ProductoVariante.objects.create(producto=cls.producto, sku='PA-50')
        StockTienda.objects.create(tienda=cls.tienda, variante=cls.variante, cantidad=3)
        cls.ana = User.objects.create_user(
            'ana@example.com', email='ana@example.com', password='clave-segura-1',
            first_name='Ana', last_name='Rojas',
        )

    def _recibo(self, *, email='ana@example.com', usuario=None, estado=ReciboVenta.ESTADO_PAGADO,
                canal=ReciboVenta.CANAL_ONLINE, dias=1, **extra):
        r = ReciboVenta.objects.create(
            canal=canal, tienda=self.tienda, total=Decimal('10000'), estado=estado,
            payment_provider=extra.pop('payment_provider', 'mercadopago'),
            payment_reference=f'tok-{uuid.uuid4().hex}',
            cliente_nombre='Ana Rojas', cliente_email=email, cliente_telefono='+56955443322',
            cliente_usuario=usuario, **extra,
        )
        ReciboVentaDetalle.objects.create(
            recibo=r, variante=self.variante, descripcion='Perfume Ana 50 ml',
            cantidad=1, precio_unitario=Decimal('10000'),
        )
        ReciboVenta.objects.filter(pk=r.pk).update(creado=timezone.now() - timedelta(days=dias))
        r.refresh_from_db()
        return r

    def _aviso(self, email='ana@example.com'):
        return AvisoStockReposicion.objects.create(variante=self.variante, email=email)

    def _resena(self, email='ana@example.com'):
        return Resena.objects.create(
            producto=self.producto, estrellas=5, texto='Me encantó', nombre_publico='Ana R.',
            cliente_email=email,
        )


# ─── Textos legales ─────────────────────────────────────────────────

@override_settings(**SIN_TRACKERS)
class TextosLegalesTests(TestCase):

    def test_politica_de_privacidad_publica_lo_que_exige_la_ley(self):
        resp = self.client.get(reverse('privacidad'))
        self.assertEqual(resp.status_code, 200)
        for texto in ('Política de privacidad', 'Versión 1.0', 'Acceso', 'Rectificación',
                      'Supresión', 'Oposición', 'Portabilidad', 'Bloqueo temporal',
                      '30 días corridos', 'Agencia de Protección de Datos Personales',
                      'fuera de Chile', 'Cuánto tiempo guardamos'):
            self.assertContains(resp, texto)

    @override_settings(RETENCION_PEDIDOS_PAGADOS_DIAS=365, RETENCION_REGISTROS_ACCESO_DIAS=45)
    def test_los_plazos_publicados_salen_de_la_configuracion(self):
        resp = self.client.get(reverse('privacidad'))
        self.assertContains(resp, '12 meses desde la compra')
        self.assertContains(resp, '45 días')

    @override_settings(EMPRESA_RAZON_SOCIAL='Blanca Contreras EIRL', EMPRESA_RUT='76.123.456-7',
                       PRIVACIDAD_EMAIL='privacidad@example.cl')
    def test_identifica_al_responsable_y_su_contacto(self):
        resp = self.client.get(reverse('privacidad'))
        self.assertContains(resp, 'Blanca Contreras EIRL')
        self.assertContains(resp, 'RUT 76.123.456-7')
        self.assertContains(resp, 'mailto:privacidad@example.cl')

    @override_settings(ECOMMERCE_GATEWAYS_ACTIVOS=['transferencia'], TRANSFERENCIA_NOMBRE='B',
                       TRANSFERENCIA_RUT='1-9', TRANSFERENCIA_CUENTA='123')
    def test_terminos_listan_los_medios_de_pago_activos(self):
        resp = self.client.get(reverse('terminos'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Términos y condiciones')
        self.assertContains(resp, 'transferencia bancaria directa')
        self.assertContains(resp, 'Ley N° 19.496')

    def test_el_pie_de_pagina_enlaza_los_textos_legales(self):
        for url in (reverse('index'), reverse('info')):
            resp = self.client.get(url)
            self.assertContains(resp, f'href="{reverse("privacidad")}"')
            self.assertContains(resp, f'href="{reverse("terminos")}"')

    def test_en_modo_landing_la_politica_sigue_disponible(self):
        from edTech.middleware import MaintenanceMiddleware
        with tempfile.TemporaryDirectory() as d:
            landing = os.path.join(d, 'LANDING_ONLY')
            open(landing, 'a').close()
            with override_settings(LANDING_ONLY_FLAG_FILE=landing,
                                   MAINTENANCE_FLAG_FILE=os.path.join(d, 'M'),
                                   TIENDA_DIRECTA_FLAG_FILE=os.path.join(d, 'T')):
                mw = MaintenanceMiddleware(lambda req: HttpResponse('PASA'))
                for path in ('/privacidad/', '/terminos/'):
                    req = RequestFactory().get(path)
                    req.user = AnonymousUser()
                    self.assertEqual(mw(req).content, b'PASA', path)


# ─── Consentimiento de cookies ─────────────────────────────────────

class ConsentimientoTests(TestCase):

    @override_settings(**TRACKERS)
    def test_nada_de_terceros_se_carga_sin_consentimiento(self):
        html = self.client.get(reverse('info')).content.decode()
        # Ninguna carga directa: todo pasa por window.IdeasConsent.
        self.assertIn('window.IdeasConsent', html)
        self.assertNotIn('<script async src="https://www.googletagmanager.com', html)
        self.assertNotIn("gtag('config', 'G-TEST123')", html)
        self.assertNotIn("fbq('init', '98765')", html)
        self.assertNotIn('cookie-notice-ok', html)   # el aviso viejo, solo "Entendido"

    @override_settings(**TRACKERS)
    def test_aviso_con_aceptar_rechazar_y_configurar(self):
        html = self.client.get(reverse('info')).content.decode()
        self.assertIn('id="consent-aviso"', html)
        for accion in ('rechazar', 'configurar', 'aceptar', 'guardar'):
            self.assertIn(f'data-consent="{accion}"', html)
        self.assertIn('id="consent-analitica"', html)
        self.assertIn('id="consent-publicidad"', html)
        # Enlace fijo en el pie para cambiar de opinion.
        self.assertIn('data-abrir-consent', html)

    @override_settings(CLARITY_PROJECT_ID='', GOOGLE_TAG_ID='', META_PIXEL_ID='98765')
    def test_solo_se_ofrecen_las_categorias_que_existen(self):
        html = self.client.get(reverse('info')).content.decode()
        self.assertNotIn('id="consent-analitica"', html)
        self.assertIn('id="consent-publicidad"', html)

    @override_settings(**SIN_TRACKERS)
    def test_sin_rastreadores_no_hay_aviso(self):
        html = self.client.get(reverse('info')).content.decode()
        self.assertNotIn('id="consent-aviso"', html)
        self.assertNotIn('window.IdeasConsent', html)
        self.assertNotIn('data-abrir-consent', html)


# ─── Derechos del titular desde la cuenta ─────────────────────────

class MisDatosTests(_ConDatos):

    def test_requiere_sesion(self):
        resp = self.client.get(reverse('ecommerce:mis_datos'))
        self.assertEqual(resp.status_code, 302)

    def test_descarga_todo_en_json(self):
        con_cuenta = self._recibo(usuario=self.ana)
        como_invitada = self._recibo()          # mismo correo, sin cuenta
        self._recibo(email='otra@example.com')  # de otra persona
        self._aviso()
        self._resena()
        self.client.force_login(self.ana)

        resp = self.client.get(reverse('ecommerce:mis_datos'))
        self.assertEqual(resp.status_code, 200)
        self.assertIn('attachment', resp['Content-Disposition'])
        datos = json.loads(resp.content)
        self.assertEqual(datos['cuenta']['correo'], 'ana@example.com')
        self.assertEqual(sorted(p['numero'] for p in datos['pedidos']),
                         sorted([con_cuenta.pk, como_invitada.pk]))
        self.assertEqual(datos['pedidos'][0]['productos'][0]['descripcion'], 'Perfume Ana 50 ml')
        self.assertEqual(len(datos['avisos_de_reposicion']), 1)
        self.assertEqual(datos['resenas'][0]['texto'], 'Me encantó')


class EliminarCuentaTests(_ConDatos):

    def setUp(self):
        self.client.force_login(self.ana)

    def _eliminar(self, password='clave-segura-1', confirmo='si'):
        return self.client.post(reverse('ecommerce:eliminar_cuenta'),
                                {'password': password, 'confirmo': confirmo})

    def _existe_ana(self):
        return User.objects.filter(pk=self.ana.pk).exists()

    def test_elimina_cuenta_avisos_y_resenas_y_anonimiza_pedidos(self):
        entregado = self._recibo(usuario=self.ana, despachado_en=timezone.now())
        factura = self._recibo(usuario=self.ana, dte_tipo=33, despachado_en=timezone.now())
        self._aviso()
        self._resena()

        resp = self._eliminar()
        self.assertRedirects(resp, reverse('ecommerce:catalogo'), fetch_redirect_response=False)
        self.assertFalse(self._existe_ana())
        self.assertFalse(AvisoStockReposicion.objects.exists())
        self.assertFalse(Resena.objects.exists())
        entregado.refresh_from_db()
        self.assertEqual((entregado.cliente_nombre, entregado.cliente_email,
                          entregado.cliente_telefono), ('', '', ''))
        self.assertEqual(entregado.total, Decimal('10000'))    # la venta queda
        factura.refresh_from_db()
        self.assertEqual(factura.cliente_email, 'ana@example.com')  # la factura no se toca
        # Quedo sin sesion.
        self.assertEqual(self.client.get(reverse('ecommerce:perfil')).status_code, 302)

    def test_contrasena_incorrecta_no_elimina(self):
        self._eliminar(password='otra')
        self.assertTrue(self._existe_ana())

    def test_sin_confirmacion_no_elimina(self):
        self._eliminar(confirmo='')
        self.assertTrue(self._existe_ana())

    def test_con_pedido_en_curso_no_elimina(self):
        self._recibo(usuario=self.ana)   # pagado y sin entregar
        self._eliminar()
        self.assertTrue(self._existe_ana())

    def test_cuenta_del_equipo_no_se_elimina_desde_la_tienda(self):
        self.ana.groups.add(Group.objects.get(name=OPERADOR))
        self._eliminar()
        self.assertTrue(self._existe_ana())

    def test_el_perfil_ofrece_descargar_y_eliminar(self):
        resp = self.client.get(reverse('ecommerce:perfil'))
        self.assertContains(resp, reverse('ecommerce:mis_datos'))
        self.assertContains(resp, reverse('ecommerce:eliminar_cuenta'))


# ─── Comando para solicitudes de clientes sin cuenta ──────────────

class ComandoDatosPersonalesTests(_ConDatos):

    def _llamar(self, *args):
        out = io.StringIO()
        call_command('datos_personales', *args, stdout=out)
        return out.getvalue()

    def test_exportar(self):
        r = self._recibo(email='invitada@example.com')
        datos = json.loads(self._llamar('exportar', 'Invitada@Example.com'))
        self.assertEqual([p['numero'] for p in datos['pedidos']], [r.pk])
        self.assertIsNone(datos['cuenta'])

    def test_suprimir_simula_si_no_se_confirma(self):
        r = self._recibo(email='invitada@example.com', despachado_en=timezone.now())
        salida = self._llamar('suprimir', 'invitada@example.com')
        self.assertIn('SIMULACIÓN', salida)
        r.refresh_from_db()
        self.assertEqual(r.cliente_email, 'invitada@example.com')

    def test_suprimir_confirmado_anonimiza(self):
        r = self._recibo(email='invitada@example.com', despachado_en=timezone.now())
        self._aviso('invitada@example.com')
        self._llamar('suprimir', 'invitada@example.com', '--confirmar')
        r.refresh_from_db()
        self.assertEqual(r.cliente_email, '')
        self.assertFalse(AvisoStockReposicion.objects.exists())

    def test_no_suprime_con_pedido_en_curso(self):
        self._recibo(email='invitada@example.com', estado=ReciboVenta.ESTADO_PENDIENTE,
                     payment_provider='transferencia')
        with self.assertRaises(CommandError):
            self._llamar('suprimir', 'invitada@example.com', '--confirmar')


# ─── Politica de conservacion ─────────────────────────────────────

@override_settings(RETENCION_PEDIDOS_NO_PAGADOS_DIAS=180, RETENCION_PEDIDOS_PAGADOS_DIAS=730,
                   RETENCION_AVISOS_CERRADOS_DIAS=180, RETENCION_AVISOS_PENDIENTES_DIAS=365,
                   RETENCION_REGISTROS_ACCESO_DIAS=90)
class PurgarDatosVencidosTests(_ConDatos):

    def _purgar(self, *args):
        out = io.StringIO()
        call_command('purgar_datos_vencidos', *args, stdout=out)
        return out.getvalue()

    def _anonimo(self, recibo):
        recibo.refresh_from_db()
        return recibo.cliente_email == '' and recibo.cliente_nombre == ''

    def test_aplica_los_plazos(self):
        R = ReciboVenta
        abandonado_viejo = self._recibo(estado=R.ESTADO_CANCELADO, dias=200)
        abandonado_reciente = self._recibo(estado=R.ESTADO_CANCELADO, dias=30)
        pagado_viejo = self._recibo(dias=800, despachado_en=timezone.now())
        pagado_reciente = self._recibo(dias=400, despachado_en=timezone.now())
        pagado_sin_entregar = self._recibo(dias=800)          # online, aun en la cola
        factura_vieja = self._recibo(dias=800, dte_tipo=33, despachado_en=timezone.now())
        por_devolver_viejo = self._recibo(estado=R.ESTADO_FALLIDO, dias=800,
                                          pago_recibido_en=timezone.now())

        aviso_cerrado_viejo = self._aviso('a@example.com')
        AvisoStockReposicion.objects.filter(pk=aviso_cerrado_viejo.pk).update(
            notificado=timezone.now() - timedelta(days=200))
        aviso_pendiente_viejo = self._aviso('b@example.com')
        AvisoStockReposicion.objects.filter(pk=aviso_pendiente_viejo.pk).update(
            creado=timezone.now() - timedelta(days=400))
        aviso_reciente = self._aviso('c@example.com')

        acceso_viejo = AccessLog.objects.create(
            user_agent='t', ip_address='127.0.0.1', username='x', http_accept='', path_info='/')
        AccessLog.objects.filter(pk=acceso_viejo.pk).update(
            attempt_time=timezone.now() - timedelta(days=100))
        acceso_reciente = AccessLog.objects.create(
            user_agent='t', ip_address='127.0.0.1', username='y', http_accept='', path_info='/')

        # Sin --aplicar no cambia nada.
        salida = self._purgar()
        self.assertIn('SIMULACIÓN', salida)
        self.assertIn('pedidos a anonimizar: 3', salida)
        self.assertFalse(self._anonimo(abandonado_viejo))

        self._purgar('--aplicar')
        self.assertTrue(self._anonimo(abandonado_viejo))
        self.assertTrue(self._anonimo(pagado_viejo))
        self.assertTrue(self._anonimo(por_devolver_viejo))
        self.assertFalse(self._anonimo(abandonado_reciente))
        self.assertFalse(self._anonimo(pagado_reciente))
        self.assertFalse(self._anonimo(pagado_sin_entregar))
        self.assertFalse(self._anonimo(factura_vieja))
        self.assertEqual(list(AvisoStockReposicion.objects.values_list('pk', flat=True)),
                         [aviso_reciente.pk])
        self.assertEqual(list(AccessLog.objects.values_list('pk', flat=True)),
                         [acceso_reciente.pk])


class EnmascararTelefonoTests(TestCase):

    def test_los_logs_no_guardan_el_numero_completo(self):
        self.assertEqual(_enmascarar('56955443322'), '569******22')
        self.assertEqual(_enmascarar('+56 9 5544 3322'), '569******22')
        self.assertEqual(_enmascarar(''), '')
