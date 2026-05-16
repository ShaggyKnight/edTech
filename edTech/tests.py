"""Tests del shell público (`base_public.html`).

Hoy verifica que el head incluya las meta tags que sostienen el SEO:
Open Graph + theme-color + manifest. Si alguien refactoriza el shell y
borra una de estas, el test lo cacha antes que silenciosamente arruinemos
los previews de WhatsApp/Instagram.
"""

from django.test import TestCase
from django.urls import reverse


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
