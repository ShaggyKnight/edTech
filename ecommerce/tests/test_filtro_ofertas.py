"""Tests del filtro `?oferta=1` del catalogo publico: solo productos
con al menos una oferta vigente y aplicable al canal online."""
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from bodega.models import StockTienda, Tienda
from catalogo.models import (
    Atributo, Familia, Oferta, Producto, ProductoVariante, ValorAtributo,
)


@override_settings(ECOMMERCE_PAYMENT_GATEWAY='mock')
class FiltroSoloOfertasTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tienda = Tienda.objects.create(nombre_organizacion='Online', activa=True)
        cls.fam = Familia.objects.create(nombre='Perfumes')

        # Producto con oferta vigente online (debe aparecer).
        cls.con_oferta_directa = Producto.objects.create(
            familia=cls.fam, nombre='Perfume Con Oferta',
            precio_base=Decimal('20000'), tiene_variantes=False,
        )
        StockTienda.objects.create(tienda=cls.tienda, producto=cls.con_oferta_directa, cantidad=5)

        # Producto sin oferta (NO debe aparecer en ?oferta=1).
        cls.sin_oferta = Producto.objects.create(
            familia=cls.fam, nombre='Perfume Sin Oferta',
            precio_base=Decimal('15000'), tiene_variantes=False,
        )
        StockTienda.objects.create(tienda=cls.tienda, producto=cls.sin_oferta, cantidad=5)

        # Producto con oferta vencida (NO debe aparecer).
        cls.con_oferta_vencida = Producto.objects.create(
            familia=cls.fam, nombre='Perfume Vencido',
            precio_base=Decimal('18000'), tiene_variantes=False,
        )
        StockTienda.objects.create(tienda=cls.tienda, producto=cls.con_oferta_vencida, cantidad=5)

        # Producto con oferta solo PRESENCIAL (NO debe aparecer en online).
        cls.con_oferta_presencial = Producto.objects.create(
            familia=cls.fam, nombre='Perfume Solo Presencial',
            precio_base=Decimal('22000'), tiene_variantes=False,
        )
        StockTienda.objects.create(tienda=cls.tienda, producto=cls.con_oferta_presencial, cantidad=5)

        # Producto con oferta vigente PAUSADA (NO debe aparecer).
        cls.con_oferta_pausada = Producto.objects.create(
            familia=cls.fam, nombre='Perfume Pausado',
            precio_base=Decimal('25000'), tiene_variantes=False,
        )
        StockTienda.objects.create(tienda=cls.tienda, producto=cls.con_oferta_pausada, cantidad=5)

        # Producto cuya oferta va por variante (no directa al producto).
        cls.con_oferta_via_variante = Producto.objects.create(
            familia=cls.fam, nombre='Perfume Oferta Variante',
            precio_base=Decimal('30000'), tiene_variantes=True,
        )
        cls.atr_vol = Atributo.objects.create(nombre='Volumen')
        cls.v_30 = ValorAtributo.objects.create(atributo=cls.atr_vol, valor='30 ml', orden=2)
        cls.variante_30 = ProductoVariante.objects.create(
            producto=cls.con_oferta_via_variante, sku='OV-30',
        )
        cls.variante_30.valores.add(cls.v_30)
        StockTienda.objects.create(tienda=cls.tienda, variante=cls.variante_30, cantidad=5)

        # Producto programado (oferta a futuro — NO debe aparecer).
        cls.con_oferta_programada = Producto.objects.create(
            familia=cls.fam, nombre='Perfume Programado',
            precio_base=Decimal('28000'), tiene_variantes=False,
        )
        StockTienda.objects.create(tienda=cls.tienda, producto=cls.con_oferta_programada, cantidad=5)

        ahora = timezone.now()

        # Ofertas
        Oferta.objects.create(
            nombre='Oferta directa vigente',
            producto=cls.con_oferta_directa,
            tipo=Oferta.TIPO_PORCENTAJE, valor=Decimal('15'),
            canal=Oferta.CANAL_AMBOS,
            fecha_inicio=ahora - timedelta(days=1),
            fecha_fin=ahora + timedelta(days=5),
            activa=True,
        )
        Oferta.objects.create(
            nombre='Oferta vencida',
            producto=cls.con_oferta_vencida,
            tipo=Oferta.TIPO_PORCENTAJE, valor=Decimal('10'),
            canal=Oferta.CANAL_AMBOS,
            fecha_inicio=ahora - timedelta(days=10),
            fecha_fin=ahora - timedelta(days=1),
            activa=True,
        )
        Oferta.objects.create(
            nombre='Oferta solo presencial',
            producto=cls.con_oferta_presencial,
            tipo=Oferta.TIPO_PORCENTAJE, valor=Decimal('10'),
            canal=Oferta.CANAL_PRESENCIAL,
            fecha_inicio=ahora - timedelta(days=1),
            fecha_fin=ahora + timedelta(days=5),
            activa=True,
        )
        Oferta.objects.create(
            nombre='Oferta pausada',
            producto=cls.con_oferta_pausada,
            tipo=Oferta.TIPO_PORCENTAJE, valor=Decimal('20'),
            canal=Oferta.CANAL_ONLINE,
            fecha_inicio=ahora - timedelta(days=1),
            fecha_fin=ahora + timedelta(days=5),
            activa=False,
        )
        Oferta.objects.create(
            nombre='Oferta sobre variante',
            variante=cls.variante_30,
            tipo=Oferta.TIPO_PORCENTAJE, valor=Decimal('30'),
            canal=Oferta.CANAL_ONLINE,
            fecha_inicio=ahora - timedelta(days=1),
            fecha_fin=ahora + timedelta(days=5),
            activa=True,
        )
        Oferta.objects.create(
            nombre='Oferta programada',
            producto=cls.con_oferta_programada,
            tipo=Oferta.TIPO_PORCENTAJE, valor=Decimal('40'),
            canal=Oferta.CANAL_AMBOS,
            fecha_inicio=ahora + timedelta(days=2),
            fecha_fin=ahora + timedelta(days=10),
            activa=True,
        )

    def setUp(self):
        self.settings_override = self.settings(ECOMMERCE_TIENDA_ID=self.tienda.pk)
        self.settings_override.enable()

    def tearDown(self):
        self.settings_override.disable()

    def test_sin_filtro_oferta_lista_todos_los_productos_con_stock(self):
        resp = self.client.get(reverse('ecommerce:catalogo'))
        self.assertEqual(resp.status_code, 200)
        # Aparecen todos (7 con stock).
        self.assertContains(resp, 'Perfume Con Oferta')
        self.assertContains(resp, 'Perfume Sin Oferta')
        self.assertContains(resp, 'Perfume Vencido')
        self.assertContains(resp, 'Perfume Solo Presencial')
        self.assertContains(resp, 'Perfume Pausado')
        self.assertContains(resp, 'Perfume Oferta Variante')
        self.assertContains(resp, 'Perfume Programado')

    def test_filtro_oferta_solo_muestra_con_oferta_vigente_online(self):
        resp = self.client.get(reverse('ecommerce:catalogo') + '?oferta=1')
        self.assertEqual(resp.status_code, 200)
        # Aparecen los 2 con oferta vigente aplicable a online.
        self.assertContains(resp, 'Perfume Con Oferta')
        self.assertContains(resp, 'Perfume Oferta Variante')
        # NO aparecen los demas.
        self.assertNotContains(resp, 'Perfume Sin Oferta')
        self.assertNotContains(resp, 'Perfume Vencido')
        self.assertNotContains(resp, 'Perfume Solo Presencial')
        self.assertNotContains(resp, 'Perfume Pausado')
        self.assertNotContains(resp, 'Perfume Programado')

    def test_filtro_oferta_setea_solo_ofertas_en_contexto(self):
        resp = self.client.get(reverse('ecommerce:catalogo') + '?oferta=1')
        self.assertTrue(resp.context['solo_ofertas'])

    def test_sin_filtro_oferta_solo_ofertas_es_false(self):
        resp = self.client.get(reverse('ecommerce:catalogo'))
        self.assertFalse(resp.context['solo_ofertas'])

    def test_filtro_oferta_muestra_titulo_apropiado(self):
        resp = self.client.get(reverse('ecommerce:catalogo') + '?oferta=1')
        self.assertContains(resp, 'Productos en oferta')
        self.assertContains(resp, 'Ofertas vigentes')

    def test_filtro_oferta_combinado_con_cat(self):
        """Si el cliente filtra por categoria Y oferta=1, intersecta."""
        otra_fam = Familia.objects.create(nombre='Uniformes')
        unif_con_oferta = Producto.objects.create(
            familia=otra_fam, nombre='Buzo Con Oferta',
            precio_base=Decimal('30000'), tiene_variantes=False,
        )
        StockTienda.objects.create(tienda=self.tienda, producto=unif_con_oferta, cantidad=3)
        Oferta.objects.create(
            nombre='Oferta uniforme',
            producto=unif_con_oferta,
            tipo=Oferta.TIPO_PORCENTAJE, valor=Decimal('10'),
            canal=Oferta.CANAL_AMBOS,
            fecha_inicio=timezone.now() - timedelta(days=1),
            fecha_fin=timezone.now() + timedelta(days=5),
            activa=True,
        )
        # Con cat=perfumes&oferta=1 → solo el perfume con oferta vigente.
        resp = self.client.get(reverse('ecommerce:catalogo') + '?cat=perfumes&oferta=1')
        self.assertContains(resp, 'Perfume Con Oferta')
        self.assertNotContains(resp, 'Buzo Con Oferta')
