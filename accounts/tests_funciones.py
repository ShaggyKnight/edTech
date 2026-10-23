"""Funciones del backoffice que un superusuario enciende o apaga
(accounts/funciones.py, FuncionesMiddleware, Administracion > Funciones)."""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse

from accounts.models import ConfiguracionSistema
from accounts.roles import ADMIN

User = get_user_model()


class FuncionesTests(TestCase):

    def setUp(self):
        self.super = User.objects.create_superuser('dueno', 'd@x.cl', 'x')
        self.admin = User.objects.create_user('blanca', password='x', is_staff=True)
        self.admin.groups.add(Group.objects.get(name=ADMIN))

    def apagar(self, **campos):
        conf = ConfiguracionSistema.actual()
        for k, v in campos.items():
            setattr(conf, k, v)
        conf.save()

    def test_todo_encendido_por_defecto(self):
        conf = ConfiguracionSistema.actual()
        self.assertTrue(conf.produccion and conf.etiquetas and conf.materiales)

    def test_solo_superusuario_entra_a_la_pantalla(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse('accounts:funciones')).status_code, 403)
        self.client.force_login(self.super)
        self.assertContains(self.client.get(reverse('accounts:funciones')), 'Funciones del sistema')

    def test_guardar_apaga_las_desmarcadas(self):
        self.client.force_login(self.super)
        resp = self.client.post(reverse('accounts:funciones'), {'etiquetas': 'on', 'materiales': 'on'})
        self.assertRedirects(resp, reverse('accounts:funciones'))
        conf = ConfiguracionSistema.actual()
        self.assertFalse(conf.produccion)
        self.assertTrue(conf.etiquetas and conf.materiales)
        self.assertEqual(conf.modificado_por, self.super)

    def test_produccion_apagada_bloquea_y_sale_del_menu(self):
        self.apagar(produccion=False)
        self.client.force_login(self.super)
        resp = self.client.get(reverse('reportes:produccion'))
        self.assertContains(resp, 'está apagada', status_code=404)
        menu = self.client.get(reverse('reportes:dashboard')).content.decode()
        self.assertNotIn(reverse('reportes:produccion'), menu)

    def test_al_encender_vuelve(self):
        self.apagar(produccion=False)
        self.apagar(produccion=True)
        self.client.force_login(self.super)
        self.assertEqual(self.client.get(reverse('reportes:produccion')).status_code, 200)

    def test_materiales_y_etiquetas_apagadas(self):
        self.apagar(materiales=False, etiquetas=False)
        self.client.force_login(self.super)
        self.assertEqual(self.client.get(reverse('bodega:lista_materiales')).status_code, 404)
        self.assertEqual(self.client.get(reverse('bodega:etiquetas_seleccionar')).status_code, 404)
        stock = self.client.get(reverse('bodega:stock')).content.decode()
        self.assertNotIn('Rollos en bodega', stock)
        self.assertNotIn(reverse('bodega:lista_materiales'), stock)

    def test_sin_sesion_va_al_login(self):
        self.apagar(produccion=False)
        resp = self.client.get(reverse('reportes:produccion'))
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse('login'), resp['Location'])
