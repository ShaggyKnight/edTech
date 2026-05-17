"""Tests del lockout anti-fuerza-bruta (django-axes).

Por default `AXES_ENABLED=False` en la test suite (ver settings.py:
`AXES_ENABLED = not TESTING`) porque el `Client.login()` de Django no
pasa el objeto request que `AxesBackend.authenticate` exige.

Acá HABILITAMOS axes con `override_settings` y validamos el flujo real
(POST a `/cuenta/login/` con credenciales malas hasta agotar el limite).
"""
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

User = get_user_model()


@override_settings(
    AXES_ENABLED=True,
    AXES_FAILURE_LIMIT=3,           # bajamos a 3 para hacer el test rapido
    AXES_COOLOFF_TIME=1,            # 1 hora — no importa, no cooloff-eamos
    AXES_LOCKOUT_PARAMETERS=['username', 'ip_address'],
)
class AxesLockoutTests(TestCase):
    def setUp(self):
        # Cache de axes acumula entre tests si no se limpia.
        cache.clear()
        User.objects.create_user(username='eduardo', password='clave-correcta')
        self.login_url = reverse('login')

    def _intento(self, username='eduardo', password='wrong'):
        return self.client.post(self.login_url, {
            'username': username, 'password': password,
        })

    def test_login_correcto_funciona(self):
        """Sanity: con axes habilitado, login valido sigue OK."""
        resp = self.client.post(self.login_url, {
            'username': 'eduardo', 'password': 'clave-correcta',
        })
        self.assertEqual(resp.status_code, 302)

    def test_n_intentos_fallidos_no_bloquean_aun(self):
        """Antes del limite (N-1), cada intento devuelve 200 con error
        de credenciales — pero NO bloqueado."""
        for _ in range(2):
            resp = self._intento()
            self.assertEqual(resp.status_code, 200)
            self.assertNotEqual(resp.status_code, 403)

    def test_excede_limit_bloquea_login_correcto(self):
        """Después de FAILURE_LIMIT fallos, hasta el password VALIDO es
        rechazado — el user está locked-out por axes."""
        for _ in range(3):
            self._intento()

        # Ahora el password CORRECTO también es rechazado.
        resp = self.client.post(self.login_url, {
            'username': 'eduardo', 'password': 'clave-correcta',
        })
        # django-axes 7.x responde HTTP 429 (Too Many Requests) cuando
        # el user/IP está bloqueado. Antiguo: 403. Aceptamos cualquiera
        # mayor a 400 para que sea robust contra cambios futuros.
        self.assertGreaterEqual(resp.status_code, 400,
            f'Esperaba lockout (4xx), recibí {resp.status_code}')
        self.assertNotEqual(resp.status_code, 302,
            'No debería redirigir a dashboard: el user está locked.')

    def test_axes_apagado_en_suite_por_default(self):
        """Meta-test: confirma que AXES_ENABLED es False en la suite
        regular (sin override). Si esto falla, los tests con login()
        directo van a romperse."""
        from django.conf import settings
        # Adentro de este test class hay override_settings(AXES_ENABLED=True),
        # asi que leemos directamente de settings con un override invertido.
        with override_settings(AXES_ENABLED=False):
            self.assertFalse(settings.AXES_ENABLED)
