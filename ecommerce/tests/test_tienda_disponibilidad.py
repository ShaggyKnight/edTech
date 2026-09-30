"""Solo se venden productos activos — regresion de la revision 2026-09-28.

`agregar` validaba que la variante estuviera activa pero no su producto,
y nada revalidaba el carrito al pagar: un producto desactivado (o una
variante de un producto desactivado) se podia comprar con un POST
directo o con un carrito armado antes de desactivarlo.
"""
from decimal import Decimal

from django.test import TestCase, override_settings
from django.urls import reverse

from bodega.models import StockTienda, Tienda
from catalogo.models import Familia, Producto, ProductoVariante
from ecommerce.cart import Cart
from ecommerce.services import ItemPedido, ProductoNoDisponibleOnline, iniciar_pedido
from pos.models import ReciboVenta


@override_settings(ECOMMERCE_GATEWAYS_ACTIVOS=['mock'])
class DisponibilidadTiendaTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.tienda = Tienda.objects.create(nombre_organizacion='Online', activa=True)
        fam = Familia.objects.create(nombre='Uniformes')
        cls.buzo = Producto.objects.create(
            familia=fam, nombre='Buzo Colegio', precio_base=Decimal('20000'),
            tiene_variantes=True,
        )
        cls.buzo_m = ProductoVariante.objects.create(producto=cls.buzo, sku='BZ-M', activa=True)
        StockTienda.objects.create(tienda=cls.tienda, variante=cls.buzo_m, cantidad=5)
        cls.perfume = Producto.objects.create(
            familia=fam, nombre='Perfume Suelto', precio_base=Decimal('9000'),
            tiene_variantes=False,
        )
        StockTienda.objects.create(tienda=cls.tienda, producto=cls.perfume, cantidad=5)

    def setUp(self):
        self.override = self.settings(ECOMMERCE_TIENDA_ID=self.tienda.pk)
        self.override.enable()

    def tearDown(self):
        self.override.disable()

    def _agregar(self, tipo, item_id, cantidad=1):
        return self.client.post(reverse('ecommerce:agregar'), {
            'tipo': tipo, 'item_id': item_id, 'cantidad': cantidad})

    def _pagar(self):
        return self.client.post(reverse('ecommerce:checkout_iniciar'), {
            'cliente_nombre': 'Ana', 'cliente_email': 'ana@example.com'})

    def _carrito(self):
        return Cart(self.client.session)

    # --- agregar ---------------------------------------------------------

    def test_no_se_agrega_una_variante_de_un_producto_desactivado(self):
        Producto.objects.filter(pk=self.buzo.pk).update(activo=False)
        self._agregar('v', self.buzo_m.pk)
        self.assertEqual(self._carrito().items_count, 0)

    def test_no_se_agrega_un_producto_desactivado(self):
        Producto.objects.filter(pk=self.perfume.pk).update(activo=False)
        self._agregar('p', self.perfume.pk)
        self.assertEqual(self._carrito().items_count, 0)

    def test_productos_activos_se_agregan_normal(self):
        self._agregar('v', self.buzo_m.pk)
        self._agregar('p', self.perfume.pk)
        self.assertEqual(self._carrito().items_count, 2)

    # --- carrito armado antes de desactivar -------------------------------

    def test_producto_desactivado_despues_de_agregarlo_no_se_puede_pagar(self):
        self._agregar('p', self.perfume.pk)
        Producto.objects.filter(pk=self.perfume.pk).update(activo=False)

        resp = self._pagar()
        self.assertRedirects(resp, reverse('ecommerce:carrito'), fetch_redirect_response=False)
        self.assertFalse(ReciboVenta.objects.exists())

        # El carrito marca la linea y ofrece quitarla.
        carrito = self.client.get(reverse('ecommerce:carrito'))
        self.assertContains(carrito, 'Ya no está disponible')
        self.assertContains(carrito, 'Quitar del carrito')
        self.client.post(reverse('ecommerce:actualizar'), {
            'key': f'p:{self.perfume.pk}', 'cantidad': 0})
        self.assertEqual(self._carrito().items_count, 0)

    def test_variante_de_producto_desactivado_en_el_carrito_no_se_puede_pagar(self):
        self._agregar('v', self.buzo_m.pk)
        Producto.objects.filter(pk=self.buzo.pk).update(activo=False)
        self._pagar()
        self.assertFalse(ReciboVenta.objects.exists())

    def test_variante_desactivada_en_el_carrito_no_se_puede_pagar(self):
        self._agregar('v', self.buzo_m.pk)
        ProductoVariante.objects.filter(pk=self.buzo_m.pk).update(activa=False)
        self._pagar()
        self.assertFalse(ReciboVenta.objects.exists())

    def test_servicio_rechaza_items_no_disponibles(self):
        Producto.objects.filter(pk=self.buzo.pk).update(activo=False)
        with self.assertRaises(ProductoNoDisponibleOnline) as ctx:
            iniciar_pedido(
                items=[ItemPedido(tipo='v', item_id=self.buzo_m.pk, cantidad=1,
                                  precio_unitario=Decimal('20000'),
                                  descuento_total=Decimal('0'))],
                cliente_nombre='X', cliente_email='x@example.com',
                return_url='http://testserver/r/',
            )
        self.assertEqual((ctx.exception.tipo, ctx.exception.item_id), ('v', self.buzo_m.pk))
        self.assertFalse(ReciboVenta.objects.exists())
