"""Tests del shell público (`base_public.html`).

Hoy verifica que el head incluya las meta tags que sostienen el SEO:
Open Graph + theme-color + manifest. Si alguien refactoriza el shell y
borra una de estas, el test lo cacha antes que silenciosamente arruinemos
los previews de WhatsApp/Instagram.
"""

import os
import tempfile

from django.contrib.auth.models import AnonymousUser
from django.core.management import call_command
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse


class ModoTiendaDirectaTests(TestCase):
    """Modo TIENDA: la home (`/`) redirige directo al catalogo, sin landing.

    El middleware cachea las rutas de los flags en __init__, asi que lo
    instanciamos a mano DESPUES del override_settings (con paths temporales)
    en vez de depender del flag real en el repo.
    """

    def _middleware(self):
        from edTech.middleware import MaintenanceMiddleware
        from django.http import HttpResponse
        return MaintenanceMiddleware(lambda req: HttpResponse('PASSTHROUGH'))

    def _request(self, path):
        req = RequestFactory().get(path)
        req.user = AnonymousUser()
        return req

    def test_modo_tienda_redirige_la_raiz_al_catalogo(self):
        with tempfile.TemporaryDirectory() as d:
            flag = os.path.join(d, 'TIENDA_DIRECTA')
            open(flag, 'a').close()
            with override_settings(
                TIENDA_DIRECTA_FLAG_FILE=flag,
                MAINTENANCE_FLAG_FILE=os.path.join(d, 'M'),
                LANDING_ONLY_FLAG_FILE=os.path.join(d, 'L'),
            ):
                resp = self._middleware()(self._request('/'))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp['Location'], reverse('ecommerce:catalogo'))

    def test_modo_tienda_no_toca_otras_rutas(self):
        with tempfile.TemporaryDirectory() as d:
            flag = os.path.join(d, 'TIENDA_DIRECTA')
            open(flag, 'a').close()
            with override_settings(
                TIENDA_DIRECTA_FLAG_FILE=flag,
                MAINTENANCE_FLAG_FILE=os.path.join(d, 'M'),
                LANDING_ONLY_FLAG_FILE=os.path.join(d, 'L'),
            ):
                resp = self._middleware()(self._request('/info/'))
        self.assertEqual(resp.content, b'PASSTHROUGH')

    def test_sin_flag_la_raiz_pasa_a_la_landing(self):
        with tempfile.TemporaryDirectory() as d:
            with override_settings(
                TIENDA_DIRECTA_FLAG_FILE=os.path.join(d, 'T'),
                MAINTENANCE_FLAG_FILE=os.path.join(d, 'M'),
                LANDING_ONLY_FLAG_FILE=os.path.join(d, 'L'),
            ):
                resp = self._middleware()(self._request('/'))
        self.assertEqual(resp.content, b'PASSTHROUGH')

    def test_mantenimiento_gana_sobre_tienda(self):
        with tempfile.TemporaryDirectory() as d:
            open(os.path.join(d, 'TIENDA_DIRECTA'), 'a').close()
            open(os.path.join(d, 'MAINTENANCE'), 'a').close()
            with override_settings(
                TIENDA_DIRECTA_FLAG_FILE=os.path.join(d, 'TIENDA_DIRECTA'),
                MAINTENANCE_FLAG_FILE=os.path.join(d, 'MAINTENANCE'),
                LANDING_ONLY_FLAG_FILE=os.path.join(d, 'L'),
            ):
                resp = self._middleware()(self._request('/'))
        self.assertEqual(resp.status_code, 503)

    def test_comando_modo_tienda_crea_flag_y_apaga_otros(self):
        with tempfile.TemporaryDirectory() as d:
            mant = os.path.join(d, 'MAINTENANCE')
            land = os.path.join(d, 'LANDING_ONLY')
            tienda = os.path.join(d, 'TIENDA_DIRECTA')
            open(land, 'a').close()  # venia en modo landing
            with override_settings(
                MAINTENANCE_FLAG_FILE=mant,
                LANDING_ONLY_FLAG_FILE=land,
                TIENDA_DIRECTA_FLAG_FILE=tienda,
            ):
                call_command('modo', 'tienda')
                self.assertTrue(os.path.exists(tienda))
                self.assertFalse(os.path.exists(land))   # se apago landing
                self.assertFalse(os.path.exists(mant))
                # Y volver a normal apaga todo.
                call_command('modo', 'normal')
                self.assertFalse(os.path.exists(tienda))


class BasePublicHeadTests(TestCase):
    def setUp(self):
        self.resp = self.client.get(reverse('index'))

    def test_status_ok(self):
        self.assertEqual(self.resp.status_code, 200)

    def test_open_graph_completo(self):
        # title/description/image: tres mínimos para que un share renderice bien.
        self.assertContains(self.resp, 'property="og:title"')
        self.assertContains(self.resp, 'property="og:description"')
        self.assertContains(self.resp, 'property="og:image"')
        self.assertContains(self.resp, 'property="og:type"')
        self.assertContains(self.resp, 'property="og:site_name" content="Ideas Boutique"')

    def test_twitter_card(self):
        self.assertContains(self.resp, 'name="twitter:card"')

    def test_theme_color_dorado_boutique(self):
        self.assertContains(self.resp, 'name="theme-color" content="#C9A96E"')

    def test_manifest_y_iconos(self):
        self.assertContains(self.resp, 'rel="manifest"')
        self.assertContains(self.resp, 'rel="icon" type="image/svg+xml"')
        self.assertContains(self.resp, 'rel="apple-touch-icon"')

    def test_viewport(self):
        self.assertContains(self.resp, 'name="viewport"')


class PaginaInfoTests(TestCase):
    """BUG-008: /info/ consolida envíos, cambios, tallas y contacto."""

    def setUp(self):
        self.resp = self.client.get(reverse('info'))

    def test_status_ok(self):
        self.assertEqual(self.resp.status_code, 200)

    def test_tiene_las_cuatro_secciones(self):
        self.assertContains(self.resp, 'id="envios"')
        self.assertContains(self.resp, 'id="cambios"')
        self.assertContains(self.resp, 'id="tallas"')
        self.assertContains(self.resp, 'id="contacto"')

    def test_footer_landing_apunta_a_info_no_a_visitanos(self):
        """El footer del landing NO debe seguir mandando los 4 helpers a
        #visitanos (que no tenía el contenido prometido)."""
        r = self.client.get(reverse('index'))
        body = r.content.decode('utf-8')
        self.assertIn('/info/#envios', body)
        self.assertIn('/info/#cambios', body)
        self.assertIn('/info/#tallas', body)
        self.assertIn('/info/#contacto', body)

    def test_pagina_tiene_chips_de_navegacion(self):
        """Tabla de contenidos interna con links a las 4 secciones."""
        self.assertContains(self.resp, 'href="#envios"')
        self.assertContains(self.resp, 'href="#cambios"')
        self.assertContains(self.resp, 'href="#tallas"')
        self.assertContains(self.resp, 'href="#contacto"')


class WhatsAppLinkTests(TestCase):
    """BUG-009: cuando PUBLIC_WHATSAPP está seteado el bloque "WhatsApp
    directo" del landing y de /info/#contacto deben rendearse como
    `<a href="https://wa.me/...">` clickeable."""

    def test_sin_setting_no_renderiza_link(self):
        # Default: settings.PUBLIC_WHATSAPP='' → texto plano, sin wa.me.
        r = self.client.get(reverse('index'))
        self.assertNotContains(r, 'https://wa.me/')

    def test_con_setting_renderiza_link_en_landing(self):
        with self.settings(PUBLIC_WHATSAPP='56912345678'):
            r = self.client.get(reverse('index'))
            self.assertContains(r, 'https://wa.me/56912345678')
            self.assertContains(r, 'target="_blank"')
            self.assertContains(r, 'rel="noopener"')

    def test_con_setting_renderiza_link_en_info(self):
        with self.settings(PUBLIC_WHATSAPP='56912345678'):
            r = self.client.get(reverse('info'))
            self.assertContains(r, 'https://wa.me/56912345678')
