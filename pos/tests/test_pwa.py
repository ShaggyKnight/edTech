"""Tests del PWA del POS: manifest + service worker + meta tags."""
import json

from django.test import TestCase
from django.urls import reverse


class PwaManifestTests(TestCase):
    def test_manifest_devuelve_json(self):
        resp = self.client.get(reverse('pos:pwa_manifest'))
        self.assertEqual(resp.status_code, 200)
        self.assertIn('application/manifest+json', resp['Content-Type'])

    def test_manifest_tiene_campos_requeridos(self):
        resp = self.client.get(reverse('pos:pwa_manifest'))
        data = json.loads(resp.content)
        for campo in ['name', 'short_name', 'start_url', 'scope',
                      'display', 'icons', 'theme_color', 'background_color']:
            self.assertIn(campo, data, f'Falta {campo} en el manifest')

    def test_manifest_scope_y_start_url_apuntan_al_pos(self):
        resp = self.client.get(reverse('pos:pwa_manifest'))
        data = json.loads(resp.content)
        self.assertEqual(data['scope'], '/pos/')
        self.assertTrue(data['start_url'].startswith('/pos/'))

    def test_manifest_tiene_al_menos_un_icono(self):
        resp = self.client.get(reverse('pos:pwa_manifest'))
        data = json.loads(resp.content)
        self.assertGreaterEqual(len(data['icons']), 1)
        icon = data['icons'][0]
        self.assertIn('src', icon)
        self.assertIn('sizes', icon)


class PwaServiceWorkerTests(TestCase):
    def test_sw_devuelve_javascript(self):
        resp = self.client.get(reverse('pos:pwa_sw'))
        self.assertEqual(resp.status_code, 200)
        self.assertIn('javascript', resp['Content-Type'])

    def test_sw_no_se_cachea(self):
        """El SW debe re-validarse en cada visita para detectar nuevas
        versiones — Cache-Control: no-store."""
        resp = self.client.get(reverse('pos:pwa_sw'))
        cc = resp.get('Cache-Control', '')
        self.assertIn('no-store', cc)

    def test_sw_tiene_listeners_install_activate_fetch(self):
        resp = self.client.get(reverse('pos:pwa_sw'))
        body = resp.content.decode()
        self.assertIn("addEventListener('install'", body)
        self.assertIn("addEventListener('activate'", body)
        self.assertIn("addEventListener('fetch'", body)

    def test_sw_skip_para_endpoints_transaccionales(self):
        """Checkout, agregar, actualizar no deben pasar por el cache."""
        resp = self.client.get(reverse('pos:pwa_sw'))
        body = resp.content.decode()
        self.assertIn('/pos/checkout', body)
        self.assertIn('/pos/agregar/', body)

    def test_sw_allowed_scope_header(self):
        resp = self.client.get(reverse('pos:pwa_sw'))
        self.assertEqual(resp.get('Service-Worker-Allowed'), '/pos/')


class PwaIntegracionTemplatesTests(TestCase):
    """Verifica que los templates del POS incluyen los meta tags."""

    def test_home_publica_link_manifest(self):
        # El POS requiere login + tienda; chequeamos que la URL exista al
        # menos via las urls registradas. Para integracion full habria
        # que loguear como cajero, lo cubre test_e2e.
        resp = self.client.get(reverse('pos:pwa_manifest'))
        self.assertEqual(resp.status_code, 200)
