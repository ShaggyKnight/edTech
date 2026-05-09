"""Tests del CRUD de ofertas desde el backoffice — Fase O.1.

Cubre: permisos por rol, listado con filtros (estado / canal / búsqueda),
creación con validaciones (fechas, valor, producto/variante exclusivos),
edición, borrado y toggle de pausa/reactivación.
"""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from catalogo.models import (
    Atributo, Familia, Oferta, Producto, ProductoVariante, ValorAtributo,
)

User = get_user_model()


def _crear_user(username, grupo=None):
    u = User.objects.create_user(username, password='x')
    if grupo:
        g, _ = Group.objects.get_or_create(name=grupo)
        u.groups.add(g)
    return u


class OfertasPermisosTests(TestCase):
    """Solo admin (o superuser) gestiona ofertas. Bodeguero y cajero no."""
    @classmethod
    def setUpTestData(cls):
        cls.cajero = _crear_user('caj', 'cajero')
        cls.bodeguero = _crear_user('bod', 'bodeguero')
        cls.admin = _crear_user('adm', 'admin')
        cls.super = User.objects.create_superuser('sup', password='x')

    def test_anonimo_no_accede(self):
        resp = self.client.get(reverse('bodega:lista_ofertas'))
        self.assertEqual(resp.status_code, 302)

    def test_cajero_no_accede(self):
        self.client.force_login(self.cajero)
        resp = self.client.get(reverse('bodega:lista_ofertas'))
        self.assertEqual(resp.status_code, 302)

    def test_bodeguero_no_accede(self):
        """El bodeguero gestiona stock, no precios — no decide ofertas."""
        self.client.force_login(self.bodeguero)
        resp = self.client.get(reverse('bodega:lista_ofertas'))
        self.assertEqual(resp.status_code, 302)

    def test_admin_si_accede(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse('bodega:lista_ofertas'))
        self.assertEqual(resp.status_code, 200)

    def test_superuser_si_accede(self):
        self.client.force_login(self.super)
        resp = self.client.get(reverse('bodega:lista_ofertas'))
        self.assertEqual(resp.status_code, 200)


class OfertasCrudTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = _crear_user('adm', 'admin')

        cls.fam = Familia.objects.create(nombre='Perfumes')
        cls.producto = Producto.objects.create(
            familia=cls.fam, nombre='Perfume X',
            precio_base=Decimal('20000'), tiene_variantes=True,
        )
        cls.atr_vol = Atributo.objects.create(nombre='Volumen')
        cls.v_30 = ValorAtributo.objects.create(atributo=cls.atr_vol, valor='30 ml', orden=2)
        cls.var_30 = ProductoVariante.objects.create(producto=cls.producto, sku='X-30')
        cls.var_30.valores.add(cls.v_30)

        cls.otro = Producto.objects.create(
            familia=cls.fam, nombre='Perfume Y',
            precio_base=Decimal('30000'), tiene_variantes=False,
        )

    def setUp(self):
        self.client.force_login(self.admin)
        self.ahora = timezone.now()

    def _post_oferta(self, **overrides):
        """Helper: POST a oferta_nueva con datos default sobreescribibles."""
        data = {
            'nombre': 'Black Friday',
            'producto': self.producto.pk,
            'variante': '',
            'tipo': Oferta.TIPO_PORCENTAJE,
            'valor': '15',
            'canal': Oferta.CANAL_AMBOS,
            'fecha_inicio': (self.ahora - timedelta(days=1)).strftime('%Y-%m-%dT%H:%M'),
            'fecha_fin':    (self.ahora + timedelta(days=7)).strftime('%Y-%m-%dT%H:%M'),
            'activa': 'on',
        }
        data.update(overrides)
        return self.client.post(reverse('bodega:oferta_nueva'), data)

    # ── Crear ──────────────────────────────────────────────────────────

    def test_crear_oferta_porcentaje_sobre_producto(self):
        resp = self._post_oferta()
        self.assertEqual(resp.status_code, 302)
        o = Oferta.objects.get()
        self.assertEqual(o.nombre, 'Black Friday')
        self.assertEqual(o.producto, self.producto)
        self.assertIsNone(o.variante)
        self.assertEqual(o.valor, Decimal('15'))

    def test_crear_oferta_sobre_variante(self):
        """Si elijo variante, producto se ignora (queda en None)."""
        resp = self._post_oferta(producto='', variante=self.var_30.pk)
        self.assertEqual(resp.status_code, 302)
        o = Oferta.objects.get()
        self.assertEqual(o.variante, self.var_30)
        self.assertIsNone(o.producto)

    def test_crear_falla_sin_producto_ni_variante(self):
        resp = self._post_oferta(producto='', variante='')
        self.assertEqual(resp.status_code, 200)  # no redirect = error en form
        self.assertContains(resp, 'producto o una variante')
        self.assertEqual(Oferta.objects.count(), 0)

    def test_crear_falla_porcentaje_mayor_a_100(self):
        resp = self._post_oferta(valor='150')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'no puede ser mayor a 100')

    def test_crear_falla_valor_negativo(self):
        resp = self._post_oferta(valor='-10')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Oferta.objects.count(), 0)

    def test_crear_falla_fecha_fin_anterior_a_inicio(self):
        resp = self._post_oferta(
            fecha_inicio=(self.ahora + timedelta(days=5)).strftime('%Y-%m-%dT%H:%M'),
            fecha_fin=(self.ahora + timedelta(days=2)).strftime('%Y-%m-%dT%H:%M'),
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'posterior a la fecha de inicio')

    def test_crear_falla_variante_no_pertenece_al_producto(self):
        resp = self._post_oferta(producto=self.otro.pk, variante=self.var_30.pk)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'no pertenece al producto')

    def test_crear_oferta_monto_fijo_acepta_valores_grandes(self):
        """Monto fijo no tiene tope de 100."""
        resp = self._post_oferta(tipo=Oferta.TIPO_MONTO, valor='5000')
        self.assertEqual(resp.status_code, 302)
        o = Oferta.objects.get()
        self.assertEqual(o.valor, Decimal('5000'))

    # ── Listar / filtros ───────────────────────────────────────────────

    def _crear_oferta_directa(self, nombre, fi_delta_dias, ff_delta_dias,
                               activa=True, canal=Oferta.CANAL_AMBOS):
        return Oferta.objects.create(
            nombre=nombre, producto=self.producto,
            tipo=Oferta.TIPO_PORCENTAJE, valor=Decimal('10'),
            canal=canal,
            fecha_inicio=self.ahora + timedelta(days=fi_delta_dias),
            fecha_fin=self.ahora + timedelta(days=ff_delta_dias),
            activa=activa,
        )

    def test_filtro_estado_vigentes(self):
        # Nombres distintivos para no chocar con las palabras "vigente" /
        # "programada" / "vencida" / "pausada" del dropdown de filtros.
        self._crear_oferta_directa('Promo-Verano', -1, +5)
        self._crear_oferta_directa('Promo-Otono', +5, +10)
        self._crear_oferta_directa('Promo-Antigua', -10, -5)
        self._crear_oferta_directa('Promo-Detenida', -1, +5, activa=False)
        resp = self.client.get(reverse('bodega:lista_ofertas') + '?estado=vigentes')
        self.assertContains(resp, 'Promo-Verano')
        self.assertNotContains(resp, 'Promo-Otono')
        self.assertNotContains(resp, 'Promo-Antigua')
        self.assertNotContains(resp, 'Promo-Detenida')

    def test_filtro_estado_programadas(self):
        self._crear_oferta_directa('Promo-Verano', -1, +5)
        self._crear_oferta_directa('Promo-Otono', +5, +10)
        resp = self.client.get(reverse('bodega:lista_ofertas') + '?estado=programadas')
        self.assertContains(resp, 'Promo-Otono')
        self.assertNotContains(resp, 'Promo-Verano')

    def test_filtro_estado_vencidas(self):
        self._crear_oferta_directa('Promo-Verano', -1, +5)
        self._crear_oferta_directa('Promo-Antigua', -10, -5)
        resp = self.client.get(reverse('bodega:lista_ofertas') + '?estado=vencidas')
        self.assertContains(resp, 'Promo-Antigua')
        self.assertNotContains(resp, 'Promo-Verano')

    def test_filtro_canal(self):
        self._crear_oferta_directa('solo-online', -1, +5, canal=Oferta.CANAL_ONLINE)
        self._crear_oferta_directa('solo-presencial', -1, +5, canal=Oferta.CANAL_PRESENCIAL)
        resp = self.client.get(reverse('bodega:lista_ofertas') + '?canal=online')
        self.assertContains(resp, 'solo-online')
        self.assertNotContains(resp, 'solo-presencial')

    def test_busqueda_por_nombre(self):
        self._crear_oferta_directa('Black Friday', -1, +5)
        self._crear_oferta_directa('Cyber Monday', -1, +5)
        resp = self.client.get(reverse('bodega:lista_ofertas') + '?q=black')
        self.assertContains(resp, 'Black Friday')
        self.assertNotContains(resp, 'Cyber Monday')

    # ── Editar ─────────────────────────────────────────────────────────

    def test_editar_oferta(self):
        o = self._crear_oferta_directa('Original', -1, +5)
        resp = self.client.post(
            reverse('bodega:oferta_editar', args=[o.pk]),
            {
                'nombre': 'Renombrada',
                'producto': self.producto.pk,
                'variante': '',
                'tipo': Oferta.TIPO_PORCENTAJE,
                'valor': '20',
                'canal': Oferta.CANAL_AMBOS,
                'fecha_inicio': (self.ahora - timedelta(days=1)).strftime('%Y-%m-%dT%H:%M'),
                'fecha_fin':    (self.ahora + timedelta(days=10)).strftime('%Y-%m-%dT%H:%M'),
                'activa': 'on',
            },
        )
        self.assertEqual(resp.status_code, 302)
        o.refresh_from_db()
        self.assertEqual(o.nombre, 'Renombrada')
        self.assertEqual(o.valor, Decimal('20'))

    # ── Borrar ─────────────────────────────────────────────────────────

    def test_borrar_oferta(self):
        o = self._crear_oferta_directa('Para borrar', -1, +5)
        resp = self.client.post(reverse('bodega:oferta_borrar', args=[o.pk]))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(Oferta.objects.filter(pk=o.pk).count(), 0)

    def test_borrar_solo_acepta_post(self):
        o = self._crear_oferta_directa('Get debe fallar', -1, +5)
        resp = self.client.get(reverse('bodega:oferta_borrar', args=[o.pk]))
        self.assertEqual(resp.status_code, 405)  # Method not allowed
        self.assertTrue(Oferta.objects.filter(pk=o.pk).exists())

    # ── Toggle (pausar / reactivar) ────────────────────────────────────

    def test_toggle_pausa_oferta_activa(self):
        o = self._crear_oferta_directa('Activa', -1, +5, activa=True)
        resp = self.client.post(reverse('bodega:oferta_toggle', args=[o.pk]))
        self.assertEqual(resp.status_code, 302)
        o.refresh_from_db()
        self.assertFalse(o.activa)

    def test_toggle_reactiva_oferta_pausada(self):
        o = self._crear_oferta_directa('Pausada', -1, +5, activa=False)
        self.client.post(reverse('bodega:oferta_toggle', args=[o.pk]))
        o.refresh_from_db()
        self.assertTrue(o.activa)

    # ── Formato de fechas ─────────────────────────────────────────────

    def test_listado_renderiza_fechas_en_formato_chileno(self):
        """El listado de ofertas debe mostrar fechas como DD-MM-AAAA HH:MM
        — la convencion chilena, no el ISO ni el m/d/Y americano."""
        from datetime import datetime
        from django.utils import timezone as djtz
        # Fecha conocida: 15 de marzo de 2026 a las 09:30 hora Chile.
        fi = djtz.make_aware(datetime(2026, 3, 15, 9, 30))
        ff = djtz.make_aware(datetime(2026, 6, 20, 18, 45))
        Oferta.objects.create(
            nombre='Otono Boutique', producto=self.producto,
            tipo=Oferta.TIPO_PORCENTAJE, valor=Decimal('15'),
            canal=Oferta.CANAL_AMBOS,
            fecha_inicio=fi, fecha_fin=ff,
        )
        resp = self.client.get(reverse('bodega:lista_ofertas'))
        self.assertContains(resp, '15-03-2026 09:30')
        self.assertContains(resp, '20-06-2026 18:45')
        # Anti-regresion: que no quede el formato viejo con barras.
        self.assertNotContains(resp, '15/03/2026')


class OfertasInlineProductoTests(TestCase):
    """Panel inline de ofertas en la pantalla de editar producto."""

    @classmethod
    def setUpTestData(cls):
        cls.admin = _crear_user('adm', 'admin')
        cls.bodeguero = _crear_user('bod', 'bodeguero')

        cls.fam = Familia.objects.create(nombre='Perfumes')
        cls.producto = Producto.objects.create(
            familia=cls.fam, nombre='Perfume Z',
            precio_base=Decimal('20000'), tiene_variantes=True,
        )
        cls.atr = Atributo.objects.create(nombre='Volumen')
        cls.v_30 = ValorAtributo.objects.create(atributo=cls.atr, valor='30 ml', orden=2)
        cls.var_30 = ProductoVariante.objects.create(producto=cls.producto, sku='Z-30')
        cls.var_30.valores.add(cls.v_30)

        cls.otro = Producto.objects.create(
            familia=cls.fam, nombre='Otro perfume',
            precio_base=Decimal('15000'), tiene_variantes=False,
        )

    def setUp(self):
        self.ahora = timezone.now()

    def _oferta(self, **kw):
        defaults = dict(
            tipo=Oferta.TIPO_PORCENTAJE, valor=Decimal('10'),
            canal=Oferta.CANAL_AMBOS,
            fecha_inicio=self.ahora - timedelta(days=1),
            fecha_fin=self.ahora + timedelta(days=5),
            activa=True,
        )
        defaults.update(kw)
        return Oferta.objects.create(**defaults)

    def test_admin_ve_oferta_directa_del_producto(self):
        self._oferta(nombre='Promo-Z-Directa', producto=self.producto)
        self.client.force_login(self.admin)
        resp = self.client.get(reverse('bodega:producto_editar', args=[self.producto.pk]))
        self.assertContains(resp, 'Promo-Z-Directa')

    def test_admin_ve_oferta_via_variante_del_producto(self):
        """Si la oferta está atada a una variante, también debe aparecer
        en la pantalla del producto padre."""
        self._oferta(nombre='Promo-Z-Variante', variante=self.var_30)
        self.client.force_login(self.admin)
        resp = self.client.get(reverse('bodega:producto_editar', args=[self.producto.pk]))
        self.assertContains(resp, 'Promo-Z-Variante')
        self.assertContains(resp, 'SKU Z-30')

    def test_admin_no_ve_oferta_de_otro_producto(self):
        self._oferta(nombre='Promo-De-Otro', producto=self.otro)
        self.client.force_login(self.admin)
        resp = self.client.get(reverse('bodega:producto_editar', args=[self.producto.pk]))
        self.assertNotContains(resp, 'Promo-De-Otro')

    def test_bodeguero_no_ve_panel_de_ofertas(self):
        """El bodeguero gestiona stock; no debería ver el panel de
        ofertas con sus precios y vigencias."""
        self._oferta(nombre='Promo-Oculta', producto=self.producto)
        self.client.force_login(self.bodeguero)
        resp = self.client.get(reverse('bodega:producto_editar', args=[self.producto.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'Promo-Oculta')
        self.assertNotContains(resp, 'Ofertas que afectan')

    def test_admin_ve_panel_vacio_con_atajo_para_crear(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse('bodega:producto_editar', args=[self.producto.pk]))
        self.assertContains(resp, 'Ofertas que afectan a este producto')
        self.assertContains(resp, 'no tiene ofertas')
        # El atajo lleva al form de oferta_nueva con el pk como query.
        url_esperada = reverse('bodega:oferta_nueva') + f'?producto={self.producto.pk}'
        self.assertContains(resp, url_esperada)

    def test_oferta_nueva_pre_selecciona_producto_via_query(self):
        self.client.force_login(self.admin)
        url = reverse('bodega:oferta_nueva') + f'?producto={self.producto.pk}'
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['form'].initial.get('producto'), self.producto.pk)

    def test_oferta_nueva_ignora_producto_inexistente(self):
        self.client.force_login(self.admin)
        url = reverse('bodega:oferta_nueva') + '?producto=999999'
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn('producto', resp.context['form'].initial)

    def test_oferta_nueva_ignora_producto_no_numerico(self):
        """Robustez frente a query strings malformadas."""
        self.client.force_login(self.admin)
        url = reverse('bodega:oferta_nueva') + '?producto=abc'
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn('producto', resp.context['form'].initial)
