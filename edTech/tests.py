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
