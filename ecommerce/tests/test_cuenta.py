"""Tests de la cuenta del cliente en la tienda online (Fase H)."""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from bodega.models import StockTienda, Tienda
from catalogo.models import Familia, Producto
from pos.models import ReciboVenta


@override_settings(ECOMMERCE_PAYMENT_GATEWAY='mock')
class RegistroLoginTests(TestCase):
    def test_registro_crea_usuario_y_loguea(self):
        resp = self.client.post(reverse('ecommerce:registro'), {
            'nombre': 'Juana',
            'apellido': 'Pérez',
            'email': 'juana@example.cl',
            'password1': 'Contrasenia-R0busta!',
            'password2': 'Contrasenia-R0busta!',
        })
        # Redirige a mis pedidos y el usuario queda autenticado.
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp['Location'], reverse('ecommerce:mis_pedidos'))

        User = get_user_model()
        user = User.objects.get(email='juana@example.cl')
        self.assertEqual(user.username, 'juana@example.cl')
        self.assertEqual(user.first_name, 'Juana')
        self.assertEqual(user.last_name, 'Pérez')

        # Autenticado: /tienda/cuenta/pedidos/ debe responder 200.
        resp = self.client.get(reverse('ecommerce:mis_pedidos'))
        self.assertEqual(resp.status_code, 200)

    def test_registro_rechaza_email_duplicado(self):
        User = get_user_model()
        User.objects.create_user(username='x@x.cl', email='x@x.cl', password='abc12345')

        resp = self.client.post(reverse('ecommerce:registro'), {
            'nombre': 'Otra', 'apellido': '',
            'email': 'x@x.cl',
            'password1': 'Contrasenia-R0busta!',
            'password2': 'Contrasenia-R0busta!',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Ya existe una cuenta')

    def test_login_redirige_a_mis_pedidos(self):
        User = get_user_model()
        User.objects.create_user(username='j@j.cl', email='j@j.cl', password='Abc12345!')

        resp = self.client.post(reverse('ecommerce:login'), {
            'username': 'j@j.cl',
            'password': 'Abc12345!',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp['Location'], reverse('ecommerce:mis_pedidos'))

    def test_mis_pedidos_requiere_login(self):
        resp = self.client.get(reverse('ecommerce:mis_pedidos'))
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse('ecommerce:login'), resp['Location'])


@override_settings(ECOMMERCE_PAYMENT_GATEWAY='mock')
class MisPedidosListadoTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.user = User.objects.create_user(
            username='carla@cliente.cl',
            email='carla@cliente.cl',
            first_name='Carla',
            password='Abc12345!',
        )
        cls.familia = Familia.objects.create(nombre='Perfumes')
        cls.tienda = Tienda.objects.create(nombre_organizacion='Tienda Online', activa=True)
        cls.producto = Producto.objects.create(
            familia=cls.familia,
            nombre='Perfume 30ml',
            precio_base=Decimal('10000'),
            tiene_variantes=False,
        )

    def _crear_recibo(self, *, usuario=None, email='', estado=ReciboVenta.ESTADO_PAGADO):
        return ReciboVenta.objects.create(
            canal=ReciboVenta.CANAL_ONLINE,
            tienda=self.tienda,
            cliente_nombre='test',
            cliente_email=email,
            cliente_usuario=usuario,
            total=Decimal('10000'),
            estado=estado,
        )

    def test_lista_por_fk_y_tambien_por_email_para_recibos_invitado(self):
        # Recibo con FK (post-registro)
        r_fk = self._crear_recibo(usuario=self.user)
        # Recibo como invitado con el mismo email (pre-registro)
        r_guest = self._crear_recibo(email='carla@cliente.cl')
        # Recibo de otro cliente (no debe aparecer)
        User = get_user_model()
        otro = User.objects.create_user(username='otro@x.cl', email='otro@x.cl', password='x')
        self._crear_recibo(usuario=otro)
        # Recibo invitado con otro email (tampoco)
        self._crear_recibo(email='ajena@x.cl')

        self.client.force_login(self.user)
        resp = self.client.get(reverse('ecommerce:mis_pedidos'))
        self.assertEqual(resp.status_code, 200)
        recibos = list(resp.context['recibos'])
        self.assertEqual({r.pk for r in recibos}, {r_fk.pk, r_guest.pk})

    def test_no_mezcla_canales(self):
        # Un recibo presencial del mismo usuario no debe colarse.
        ReciboVenta.objects.create(
            canal=ReciboVenta.CANAL_PRESENCIAL,
            tienda=self.tienda,
            cliente_email='carla@cliente.cl',
            cliente_usuario=self.user,
            total=Decimal('5000'),
            estado=ReciboVenta.ESTADO_PAGADO,
        )
        self.client.force_login(self.user)
        resp = self.client.get(reverse('ecommerce:mis_pedidos'))
        self.assertEqual(list(resp.context['recibos']), [])


@override_settings(
    ECOMMERCE_PAYMENT_GATEWAY='mock',
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
)
class CheckoutLogueadoTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.user = User.objects.create_user(
            username='pedro@cliente.cl',
            email='pedro@cliente.cl',
            first_name='Pedro',
            last_name='Soto',
            password='Abc12345!',
        )
        cls.familia = Familia.objects.create(nombre='Perfumes')
        cls.tienda = Tienda.objects.create(nombre_organizacion='Tienda Online', activa=True)
        cls.producto = Producto.objects.create(
            familia=cls.familia,
            nombre='Perfume 30ml',
            precio_base=Decimal('12000'),
            tiene_variantes=False,
        )
        StockTienda.objects.create(tienda=cls.tienda, producto=cls.producto, cantidad=5)

    def test_checkout_prellena_email_y_nombre(self):
        with self.settings(ECOMMERCE_TIENDA_ID=self.tienda.pk):
            self.client.force_login(self.user)
            self.client.post(reverse('ecommerce:agregar'), {
                'tipo': 'p', 'item_id': self.producto.pk, 'cantidad': 1,
            })
            resp = self.client.get(reverse('ecommerce:checkout'))
            self.assertEqual(resp.status_code, 200)
            # El input del formulario debe traer los datos del usuario.
            self.assertContains(resp, 'value="Pedro Soto"')
            self.assertContains(resp, 'value="pedro@cliente.cl"')

    def test_iniciar_pedido_guarda_fk_cliente_usuario(self):
        with self.settings(ECOMMERCE_TIENDA_ID=self.tienda.pk):
            self.client.force_login(self.user)
            self.client.post(reverse('ecommerce:agregar'), {
                'tipo': 'p', 'item_id': self.producto.pk, 'cantidad': 1,
            })
            resp = self.client.post(reverse('ecommerce:checkout_iniciar'), {
                'cliente_nombre': 'Pedro Soto',
                'cliente_email': 'pedro@cliente.cl',
                'cliente_rut': '',
                'cliente_telefono': '',
                'cliente_direccion': 'Av Z 456',
            })
            self.assertEqual(resp.status_code, 302)
            recibo = ReciboVenta.objects.get()
            self.assertEqual(recibo.cliente_usuario_id, self.user.pk)

    def test_invitado_no_rompe_checkout(self):
        """Checkout sin login sigue funcionando y deja FK en None."""
        with self.settings(ECOMMERCE_TIENDA_ID=self.tienda.pk):
            self.client.post(reverse('ecommerce:agregar'), {
                'tipo': 'p', 'item_id': self.producto.pk, 'cantidad': 1,
            })
            resp = self.client.post(reverse('ecommerce:checkout_iniciar'), {
                'cliente_nombre': 'Invitado',
                'cliente_email': 'inv@x.cl',
                'cliente_rut': '',
                'cliente_telefono': '',
                'cliente_direccion': '',
            })
            self.assertEqual(resp.status_code, 302)
            recibo = ReciboVenta.objects.get()
            self.assertIsNone(recibo.cliente_usuario_id)
